import operator
import json
import math
import random
import re
from typing import TypedDict, Annotated, List, Dict
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from google import genai


def _extract_json_array(text: str):
    if not text:
        return []

    cleaned = text.strip().replace("```json", "").replace("```", "").strip()
    start = cleaned.find('[')
    end = cleaned.rfind(']')
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]

    try:
        return json.loads(cleaned)
    except Exception:
        # Escape stray backslashes that are not part of valid JSON escape sequences.
        repaired = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', cleaned)
        try:
            return json.loads(repaired)
        except Exception as e:
            print(f"Error parsing JSON array payload: {e}")
            return []

class LessonState(TypedDict):
    track_title: str
    module_title: str
    lesson_title: str
    learner_summary: str
    sublessons: List[str]
    sublesson_contents: Annotated[List[Dict[str, str]], operator.add]
    final_content: str

class SubtopicState(TypedDict):
    track_title: str
    module_title: str
    lesson_title: str
    learner_summary: str
    subtopic: str

def generate_subtopics(state: LessonState):
    # Import inside function to avoid circular import issues
    from .services import client, DEFAULT_MODEL
    
    prompt = f"""
    You are an expert curriculum designer. We need to create detailed subtopics for this lesson.
    Track: {state['track_title']}
    Module: {state['module_title']}
    Lesson: {state['lesson_title']}
    
    Learner Background:
    {state.get('learner_summary', '')}
    
    Please break this lesson down into 3-5 very specific, deep-dive sublessons/topics.
    Return ONLY a JSON list of strings, e.g. ["Subtopic 1", "Subtopic 2", "Subtopic 3"]. Do not include markdown formatting blocks.
    """
    
    response = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    
    try:
        subtopics = json.loads(response.text)
        if not isinstance(subtopics, list):
             subtopics = [state['lesson_title']]
    except Exception as e:
        print(f"Error parsing subtopics: {e}")
        subtopics = [state['lesson_title']]
        
    return {"sublessons": subtopics}

def map_subtopics(state: LessonState):
    return [
        Send(
            "generate_single_subtopic",
            {
                "track_title": state["track_title"],
                "module_title": state["module_title"],
                "lesson_title": state["lesson_title"],
                "learner_summary": state.get("learner_summary", ""),
                "subtopic": subtopic
            }
        )
        for subtopic in state["sublessons"]
    ]

def generate_single_subtopic(state: SubtopicState):
    from .services import client, DEFAULT_MODEL
    
    subtopic = state["subtopic"]
    
    personalization_prompt = ""
    if state.get("learner_summary"):
        personalization_prompt = f"""
        ### USER PERSONALIZATION CONTEXT (CRITICAL):
        The following is a summary of the learner's existing background relative to this track:
        \"\"\"{state['learner_summary']}\"\"\"
        
        Use this context to make the lesson more relatable and effective:
        1. **Analogies**: Where possible, compare new concepts to technologies or concepts the user already knows.
        2. **Efficiency**: If the user is an expert in a related field, skip the basics and focus on the deltas and specific implementation details of this track.
        3. **Tone**: Use an 'expert-to-expert' tone if the summary indicates high seniority.
        """

    prompt = f"""
    You are an expert instructor writing a section of a larger lesson.
    Track: {state['track_title']}
    Module: {state['module_title']}
    Lesson: {state['lesson_title']}
    Subtopic/Section: {subtopic}
    
    {personalization_prompt}
    
    Provide a detailed, rigorous, and highly educational explanation specifically for this subtopic.
    
    ### Visual & Technical Guidelines:
    1. **Formatting**: Strictly follow Markdown hierarchies. Start your section with `### {subtopic}`.
    2. **Code Block Protocol (CRITICAL)**: 
       - **Triple Backticks (```)**: Use ONLY for multi-line, executable code blocks. They MUST have a language tag.
       - **Single Backticks (`)**: Use for inline technical terms. Integrate them INTO existing sentences.
       - **Unbroken Paragraphs**: NEVER break a sentence or start a new line just because it contains a backtick. Technical content must be a single, flowing paragraph.
    3. **Markdown Tables (Mandatory for Comparisons)**:
       - You MUST use the full `|` delimiter syntax.
    4. **Code Quality**: Provide robust, multi-line code examples with helpful comments.
    5. **Understanding (Crucial)**: 
       - For every core technical concept, include a **Mermaid diagram**.
       - **No Block Chatter**: The Mermaid block MUST start immediately with the graph type (e.g., `graph TD`). NO titles, NO comments, NO plain text inside the backticks.
       - **Mermaid Golden Rule**: ALWAYS use explicit alphanumeric IDs and wrap labels in double quotes. 
         FORMAT: `ID["Label Text"]` (e.g., `A["State Change"] --> B["Proxy Intercept"]`).
       - **Nested Content (STRICT BAN)**: NEVER use quotes (`"` or `'`), backticks (`` ` ``), parentheses `()`, or brackets `[]` inside a Mermaid label. Use plain descriptive text ONLY.
       - **Arrows**: Use standard lowercase arrows: `-->`, `---`, `-.-`, `==>`, `--x`, `--o`.
       - **Complexity**: Keep diagrams focused (max 8 nodes).
    6. **Tone**: Rigorous and professional.
    7. **Images**: Can use relevant Images. The image should be completely relevant to the chapter and content.
    """
    
    response = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            temperature=0.4,
        ),
    )
    
    return {"sublesson_contents": [{"subtopic": subtopic, "content": response.text}]}

def aggregate_content(state: LessonState):
    ordered_contents = []
    sublessons = state.get("sublessons", [])
    contents_map = {item["subtopic"]: item["content"] for item in state.get("sublesson_contents", [])}
    
    for sub in sublessons:
        if sub in contents_map:
            ordered_contents.append(contents_map[sub])
            
    # Combine the generated contents into one final cohesive string
    final_text = "\n\n".join(ordered_contents)
    return {"final_content": final_text}

# Build LangGraph workflow globally
lesson_workflow = StateGraph(LessonState)
lesson_workflow.add_node("generate_subtopics", generate_subtopics)
lesson_workflow.add_node("generate_single_subtopic", generate_single_subtopic)
lesson_workflow.add_node("aggregate_content", aggregate_content)

lesson_workflow.add_edge(START, "generate_subtopics")
lesson_workflow.add_conditional_edges("generate_subtopics", map_subtopics, ["generate_single_subtopic"])
lesson_workflow.add_edge("generate_single_subtopic", "aggregate_content")
lesson_workflow.add_edge("aggregate_content", END)

lesson_generator_app = lesson_workflow.compile()


# --- MODULE LEVEL WORKFLOW ---

# --- ASSESSMENT LEVEL WORKFLOW ---

class AssessmentState(TypedDict):
    track_title: str
    module_title: str
    assessment_questions: List[dict]

def generate_assessment_logic(state: AssessmentState):
    from .services import client, DEFAULT_MODEL
    import json
    
    if not client:
        return {"assessment_questions": []}
        
    prompt = f"""
    You are an elite technical examiner. Create a rigorous, high-stakes assessment for:
    Track: {state['track_title']}
    Module: {state['module_title']}
    
    ### Dynamic Guidelines:
    1. **Question Volume**: Do not stick to a fixed number. Decide the optimal volume (between 3 to 10 questions) based on the depth of the module.
    2. **Heuristic Variety**: Integrate a mix of the following types:
       - `mcq`: Standard multiple choice (exactly 1 correct).
       - `boolean`: True/False style (2 options).
       - `multi_select`: Technical scenarios where multiple options might be correct (>=1 correct).
    
    ### Strict JSON Schema:
    Return a JSON array of objects:
    [
        {{
            "question": "The question text",
            "type": "mcq" | "boolean" | "multi_select",
            "options": ["Option 1", "Option 2", ...],
            "correct_answer": [0, 2], // List of indices of the correct options. Use a list even for mcq/boolean.
            "explanation": "Detailed technical justification"
        }}
    ]
    
    Make the questions highly challenging and focused on real-world engineering constraints. 
    Do not include markdown formatting blocks.
    """
    
    response = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    
    try:
        return {"assessment_questions": json.loads(response.text)}
    except Exception as e:
        print(f"Error parsing dynamic assessment JSON: {e}")
        return {"assessment_questions": []}

assessment_workflow = StateGraph(AssessmentState)
assessment_workflow.add_node("generate_assessment_logic", generate_assessment_logic)
assessment_workflow.add_edge(START, "generate_assessment_logic")
assessment_workflow.add_edge("generate_assessment_logic", END)
assessment_generator_app = assessment_workflow.compile()


class ModuleState(TypedDict):
    learner_id: str
    track_id: str
    module_id: str
    track_title: str
    module_title: str
    learner_summary: str
    needs_assessment: bool
    lessons_to_generate: List[Dict[str, str]]
    
    generated_lessons: Annotated[List[Dict[str, str]], operator.add]
    assessment_questions: List[dict]

class LessonMapState(TypedDict):
    lesson_id: str
    track_title: str
    module_title: str
    lesson_title: str
    learner_summary: str

def generate_assessment_node(state: ModuleState):
    if not state.get("needs_assessment"):
        return {"assessment_questions": []}

    initial_state = {
        "track_title": state["track_title"],
        "module_title": state["module_title"],
        "assessment_questions": []
    }
    result = assessment_generator_app.invoke(initial_state)
    return {"assessment_questions": result.get("assessment_questions", [])}

def map_module_lessons(state: ModuleState):
    return [
        Send(
            "generate_module_lesson_node",
            {
                "lesson_id": l["id"],
                "track_title": state["track_title"],
                "module_title": state["module_title"],
                "lesson_title": l["title"],
                "learner_summary": state["learner_summary"],
            }
        )
        for l in state.get("lessons_to_generate", [])
    ]

def generate_module_lesson_node(state: LessonMapState):
    # Reuse the lesson_generator_app for each lesson
    initial_state = {
        "track_title": state["track_title"],
        "module_title": state["module_title"],
        "lesson_title": state["lesson_title"],
        "learner_summary": state["learner_summary"],
        "sublesson_contents": []
    }
    result = lesson_generator_app.invoke(initial_state)
    return {"generated_lessons": [{"id": state["lesson_id"], "content": result.get("final_content", "")}]}

def store_module_results_node(state: ModuleState):
    from apps.curriculum.models import Lesson, Module, PersonalizedLessonContent
    from apps.accounts.models import Learner
    
    try:
        # Save Lessons
        learner = Learner.objects.get(id=state["learner_id"])
        for item in state.get("generated_lessons", []):
            try:
                lesson_obj = Lesson.objects.get(id=item["id"])
                PersonalizedLessonContent.objects.update_or_create(
                    lesson=lesson_obj,
                    learner=learner,
                    defaults={"content": item["content"]}
                )
            except Exception as e:
                print(f"Error saving lesson {item['id']}: {e}")
                
        # Save Assessment
        if state.get("assessment_questions"):
            module = Module.objects.get(id=state["module_id"])
            assessment = getattr(module, 'assessment', None)
            if assessment and not assessment.questions_data:
                assessment.questions_data = state["assessment_questions"]
                assessment.save()
                print(f"Stored Assessment for module {state['module_title']}")
                
    except Exception as e:
        print(f"Error storing module results: {e}")
        
    return state

module_workflow = StateGraph(ModuleState)
module_workflow.add_node("generate_assessment_node", generate_assessment_node)
module_workflow.add_node("generate_module_lesson_node", generate_module_lesson_node)
module_workflow.add_node("store_module_results_node", store_module_results_node)

module_workflow.add_edge(START, "generate_assessment_node")

# To ensure the process closes elegantly when no lessons are needed
def branch_to_store_or_lessons(state: ModuleState):
    if len(state.get("lessons_to_generate", [])) == 0:
        return "store_module_results_node"
    return map_module_lessons(state)

module_workflow.add_conditional_edges("generate_assessment_node", branch_to_store_or_lessons, ["generate_module_lesson_node", "store_module_results_node"])

module_workflow.add_edge("generate_module_lesson_node", "store_module_results_node")
module_workflow.add_edge("store_module_results_node", END)

module_generator_app = module_workflow.compile()


# --- ROADMAP LEVEL WORKFLOW ---

class RoadmapState(TypedDict):
    goal: str
    admin_id: str
    roadmap_title: str
    roadmap_description: str
    steps: List[Dict[str, str]]
    roadmap_id: str

def generate_roadmap_structure(state: RoadmapState):
    from .services import client, DEFAULT_MODEL
    
    prompt = f"""
    You are an elite career coach and curriculum architect.
    The user wants to become: "{state['goal']}".
    
    Design a comprehensive career roadmap. 
    Break it down into 5-8 major steps.
    Each step should represent a significant milestone/learning track.
    
    Return the result strictly as a JSON object:
    {{
        "title": "Roadmap Title",
        "description": "Comprehensive description of the path",
        "steps": [
            {{
                "title": "Step Title",
                "description": "What this milestone covers and why it's important"
            }}
        ]
    }}
    
    Do not include markdown formatting blocks.
    """
    
    response = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    
    try:
        data = json.loads(response.text)
        return {
            "roadmap_title": data.get("title", f"Roadmap for {state['goal']}"),
            "roadmap_description": data.get("description", ""),
            "steps": data.get("steps", [])
        }
    except Exception as e:
        print(f"Error parsing roadmap JSON: {e}")
        return {"steps": []}

def store_generated_roadmap(state: RoadmapState):
    from apps.curriculum.models import Roadmap, RoadmapStep
    from apps.accounts.models import Learner
    
    try:
        admin = Learner.objects.filter(id=state["admin_id"]).first()
        
        roadmap = Roadmap.objects.create(
            title=state["roadmap_title"],
            description=state["roadmap_description"],
            created_by=admin
        )
        
        for idx, step_data in enumerate(state["steps"]):
            RoadmapStep.objects.create(
                roadmap=roadmap,
                title=step_data.get("title", f"Step {idx+1}"),
                description=step_data.get("description", ""),
                order=idx
            )
            
        return {"roadmap_id": str(roadmap.id)}
    except Exception as e:
        print(f"Error storing roadmap: {e}")
        return {}

roadmap_workflow = StateGraph(RoadmapState)
roadmap_workflow.add_node("generate_roadmap_structure", generate_roadmap_structure)
roadmap_workflow.add_node("store_generated_roadmap", store_generated_roadmap)

roadmap_workflow.add_edge(START, "generate_roadmap_structure")
roadmap_workflow.add_edge("generate_roadmap_structure", "store_generated_roadmap")
roadmap_workflow.add_edge("store_generated_roadmap", END)

roadmap_generator_app = roadmap_workflow.compile()


# --- FINAL ASSESSMENT WORKFLOW ---

class FinalAssessmentModuleQuestionState(TypedDict):
    scope_type: str
    scope_title: str
    scope_description: str
    module_titles: List[str]
    question_count: int
    previous_questions: List[str]
    attempt_number: int


class FinalAssessmentState(TypedDict):
    scope_type: str
    scope_title: str
    scope_description: str
    module_titles: List[str]
    question_count_per_module: int
    module_batches: List[List[str]]
    previous_questions: List[str]
    attempt_number: int
    generated_question_sets: Annotated[List[List[dict]], operator.add]
    final_questions: List[dict]
    time_limit_minutes: int
    passing_score: int


def prepare_final_assessment_modules(state: FinalAssessmentState):
    module_count = max(len(state.get("module_titles", [])), 1)
    total_target = 18 if state.get("scope_type") == "track" else 24
    question_count_per_module = max(2, math.ceil(total_target / module_count))
    module_titles = state.get("module_titles", [])
    batch_size = 3 if module_count >= 6 else 2
    module_batches = [
        module_titles[index:index + batch_size]
        for index in range(0, len(module_titles), batch_size)
    ] or [module_titles]
    return {
        **state,
        "question_count_per_module": question_count_per_module,
        "module_batches": module_batches,
    }


def map_final_assessment_modules(state: FinalAssessmentState):
    return [
        Send(
            "generate_final_module_questions",
            {
                "scope_type": state["scope_type"],
                "scope_title": state["scope_title"],
                "scope_description": state["scope_description"],
                "module_titles": module_batch,
                "question_count": max(2, len(module_batch) * state.get("question_count_per_module", 2)),
                "previous_questions": state.get("previous_questions", []),
                "attempt_number": state.get("attempt_number", 1),
            }
        )
        for module_batch in state.get("module_batches", [])
    ]


def generate_final_module_questions(state: FinalAssessmentModuleQuestionState):
    from .services import client, DEFAULT_MODEL

    if not client:
        return {"generated_question_sets": [[]]}

    prompt = f"""
    You are an elite certification examiner.

    Create advanced final-evaluation questions for one module of a larger {state['scope_type']} certification.

    Scope title: {state['scope_title']}
    Scope description: {state['scope_description']}
    Module coverage batch: {json.dumps(state['module_titles'])}
    Attempt number: {state.get('attempt_number', 1)}

    Previously used questions that MUST NOT be repeated or trivially reworded:
    {json.dumps(state.get('previous_questions', []), indent=2)}

    Requirements:
    1. Generate exactly {state.get('question_count', 2)} high-quality questions covering all modules in this batch.
    2. Questions must be significantly harder than standard module quizzes.
    3. Favor scenario-based engineering judgment, debugging tradeoffs, architecture reasoning, and failure analysis.
    4. Use these types only: `mcq`, `boolean`, `multi_select`.
    5. Do not repeat previously used questions, answer structures, or near-duplicates.
    6. Distribute questions across the modules in the batch instead of focusing on only one.

    Return only a JSON array:
    [
      {{
        "question": "Question text",
        "type": "mcq",
        "options": ["A", "B", "C", "D"],
        "correct_answer": [1],
        "explanation": "Why this is correct",
        "module_titles": {json.dumps(state['module_titles'])}
      }}
    ]
    """

    response = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )

    parsed = _extract_json_array(response.text)
    if not isinstance(parsed, list):
        parsed = []

    return {"generated_question_sets": [parsed]}


def aggregate_final_assessment_questions(state: FinalAssessmentState):
    question_sets = state.get("generated_question_sets", [])
    questions = [question for question_set in question_sets for question in question_set]
    random.shuffle(questions)

    question_count = len(questions)
    time_limit_minutes = min(45, max(20, math.ceil(question_count * 1.5)))
    passing_score = 85

    return {
        "final_questions": questions,
        "time_limit_minutes": time_limit_minutes,
        "passing_score": passing_score,
    }


final_assessment_workflow = StateGraph(FinalAssessmentState)
final_assessment_workflow.add_node("prepare_final_assessment_modules", prepare_final_assessment_modules)
final_assessment_workflow.add_node("generate_final_module_questions", generate_final_module_questions)
final_assessment_workflow.add_node("aggregate_final_assessment_questions", aggregate_final_assessment_questions)
final_assessment_workflow.add_edge(START, "prepare_final_assessment_modules")
final_assessment_workflow.add_conditional_edges("prepare_final_assessment_modules", map_final_assessment_modules, ["generate_final_module_questions"])
final_assessment_workflow.add_edge("generate_final_module_questions", "aggregate_final_assessment_questions")
final_assessment_workflow.add_edge("aggregate_final_assessment_questions", END)

final_assessment_generator_app = final_assessment_workflow.compile()
