import os
import json
from google import genai
from django.conf import settings

try:
    api_key = getattr(settings, 'GOOGLE_API_KEY', os.environ.get('GOOGLE_API_KEY'))
    if api_key:
        client = genai.Client(api_key=api_key)
    else:
        client = genai.Client() 
except Exception as e:
    print(f"Failed to initialize GenAI client: {e}")
    client = None

DEFAULT_MODEL = "gemini-3-flash-preview"


def generate_track_curriculum(topic: str, learner_summary: str = None) -> dict:
    """
    Generates a structured curriculum (Track -> Modules -> Lessons) for a given topic.
    """
    if not client:
        return {}
        
    personalization_context = ""
    if learner_summary:
        personalization_context = f"""
        ### LEARNER BACKGROUND CONTEXT:
        {learner_summary}
        
        ### CUSTOMIZATION INSTRUCTIONS:
        1. **Avoid Redundancy**: If the learner is already expert in parts of "{topic}", shift the focus to advanced or delta concepts.
        2. **Bridge Gaps**: Use their existing tech stack to create a faster learning path (e.g., if they know SQL, don't teach "What is a database", teach "How this tech manages data compared to SQL").
        3. **Tone & Depth**: Adjust the complexity of modules based on their seniority.
        """

    prompt = f"""
    You are an expert curriculum designer. The user wants to learn about: "{topic}".
    {personalization_context}
    
    Design a comprehensive learning track. Break it down into 3-5 Modules.
    For each Module, provide 3-5 Lessons.
    
    Return the result strictly as a JSON object matching this schema:
    {{
        "title": "Track Title",
        "description": "Short description of the track",
        "modules": [
            {{
                "title": "Module Title",
                "description": "What this module covers",
                "lessons": [
                    {{
                        "title": "Lesson Title"
                    }}
                ]
            }}
        ]
    }}
    
    Do not include any Markdown formatting blocks (e.g. ```json) in your response, just the raw JSON string.
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
        return json.loads(response.text)
    except Exception as e:
        print(f"Error parsing JSON from Gemini: {e}")
        return {}


def generate_lesson_content(track_title: str, module_title: str, lesson_title: str, learner_summary: str = None) -> str:
    """
    Generates detailed, rigorous markdown content for a specific lesson using LangGraph.
    It breaks the lesson into subtopics and concurrently generates content for each subtopic.
    """
    if not client:
        return "AI Client not configured."
        
    from .langgraph_workflows import lesson_generator_app

    initial_state = {
        "track_title": track_title,
        "module_title": module_title,
        "lesson_title": lesson_title,
        "learner_summary": learner_summary or "",
        "sublesson_contents": []
    }
    
    try:
        result = lesson_generator_app.invoke(initial_state)
        return result.get("final_content", "Failed to generate lesson content.")
    except Exception as e:
        print(f"LangGraph execution error: {e}")
        return "An error occurred while generating the detailed lesson content."



def analyze_assessment_failure(module_title: str, questions_data: list, user_answers_data: dict) -> dict:
    """
    Analyzes a failed test, provides feedback, and structures a remedial module.
    user_answers_data expected format: { "0": 1, "1": 3, ... } (question index to selected option index)
    Returns a dict with feedback and remedial_module details.
    """
    if not client:
        return {}
        
    prompt = f"""
    A student failed the assessment for the module: '{module_title}'.
    Here are the original questions and correct answers:
    {json.dumps(questions_data, indent=2)}
    
    Here are the user's answers (mapping question index to option index they chose):
    {json.dumps(user_answers_data, indent=2)}
    
    Perform two tasks based on what they got wrong:
    1. Write an encouraging feedback message explaining what core concepts they seem to be confused about.
    2. Design a single new "Remedial Module" containing 2 or 3 lessons that specifically target ONLY the concepts they failed.
    
    Return strictly as a JSON object matching this schema:
    {{
        "feedback": "Your markdown formatted feedback explaining their mistakes...",
        "remedial_module": {{
            "title": "Remedial: [Topic Name]",
            "description": "Focusing on [weak spots]",
            "lessons": [
                {{ "title": "Targeted Lesson 1" }},
                {{ "title": "Targeted Lesson 2" }}
            ]
        }}
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
        return json.loads(response.text)
    except Exception as e:
        print(f"Error parsing remedial JSON: {e}")
        return {}


def _extract_text_from_file(file_path: str) -> str:
    """Extracts plain text from PDF and DOCX files."""
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    
    try:
        if ext == ".pdf":
            import PyPDF2
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    content = page.extract_text()
                    if content:
                        text += content + "\n"
        elif ext in [".docx", ".doc"]:
            import docx
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        else:
            # Fallback for plain text
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
    except Exception as e:
        print(f"Extraction failed for {file_path}: {e}")
        return ""
    
    return text.strip()


def analyze_resume_for_background(resume_path: str) -> str:
    """
    Analyzes a candidate's background by extracting text from their resume.
    Returns a summary text used for both structural curriculum generation AND lesson content personalization.
    """
    if not client:
        return "Analysis disabled: AI client not configured."
        
    resume_text = _extract_text_from_file(resume_path)
    
    if not resume_text:
        return "Standard Analysis: Profile loaded (Resume content could not be extracted)."

    try:
        prompt = f"""
        You are an AI technical mentor. Analyze the following resume text.
        
        ### RESUME:
        {resume_text[:4000]}
        
        ### TASK:
        Provide a concise technical summary of this person.
        Identify:
        1. Their 3 strongest technologies.
        2. Their general seniority level.
        3. Tech stacks they are NOT familiar with but are related to their field.
        
        Return a single paragraph for use as LLM context.
        """
        
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                temperature=0.2,
            ),
        )
        return response.text
        
    except Exception as e:
        print(f"Error analyzing background: {e}")
        return "User profile loaded with standard settings."


def analyze_resume_for_curriculum(resume_path: str, curriculum_overview: str) -> str:
    """
    DEPRECATED: Use the more general analyze_resume_for_background instead.
    """
    return analyze_resume_for_background(resume_path)


def generate_custom_roadmap_step(instruction: str, current_roadmap: dict) -> dict:
    """
    Generates a new roadmap step based on a natural language instruction and the current roadmap context.
    """
    if not client:
        return {}
    
    prompt = f"""
    You are an elite curriculum architect.
    Current Roadmap: "{current_roadmap.get('title')}"
    Description: {current_roadmap.get('description')}
    
    Existing Milestones:
    {json.dumps([s.get('title') for s in current_roadmap.get('steps', [])], indent=2)}
    
    USER REQUEST: "{instruction}"
    
    Based on this request, generate a NEW milestone step that fits this roadmap.
    It should be precise, technical, and high-impact.
    
    Return strictly as a JSON object:
    {{
        "title": "Step Title",
        "description": "Step Description"
    }}
    
    Do not include markdown blocks.
    """
    
    try:
        response = client.models.generate_content(
            model=DEFAULT_MODEL,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.4,
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error generating custom step: {e}")
        return {}
