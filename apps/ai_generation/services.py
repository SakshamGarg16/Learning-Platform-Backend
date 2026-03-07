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


def generate_track_curriculum(topic: str) -> dict:
    """
    Generates a structured curriculum (Track -> Modules -> Lessons) for a given topic.
    Returns a dictionary parsed from the JSON response.
    """
    if not client:
        return {}
        
    prompt = f"""
    You are an expert curriculum designer. The user wants to learn about: "{topic}".
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
        print(f"Raw response: {response.text}")
        return {}


def generate_lesson_content(track_title: str, module_title: str, lesson_title: str) -> str:
    """
    Generates detailed, rigorous markdown content for a specific lesson.
    """
    if not client:
        return "AI Client not configured."
        
    prompt = f"""
    You are an expert instructor.
    Track: {track_title}
    Module: {module_title}
    Lesson: {lesson_title}
    
    Provide a detailed, rigorous, and highly educational explanation for this lesson.
    
    ### Visual & Technical Guidelines:
    1. **Formatting**: Strictly follow Markdown hierarchies.
    2. **Code Block Protocol (CRITICAL)**: 
       - **Triple Backticks (```)**: Use ONLY for multi-line, executable code blocks. They MUST have a language tag.
       - **Single Backticks (`)**: Use for inline technical terms. Integrate them INTO existing sentences.
       - **Unbroken Paragraphs**: NEVER break a sentence or start a new line just because it contains a backtick. Technical content must be a single, flowing paragraph.
    3. **Markdown Tables (Mandatory for Comparisons)**:
       - You MUST use the full `|` delimiter syntax.
       - Example:
         | Feature | Description |
         | :--- | :--- |
         | Item | Explanation |
    4. **Code Quality**: Provide robust, multi-line code examples with helpful comments.
    5. **Understanding (Crucial)**: 
       - For every core technical concept, include a **Mermaid diagram**.
       - **No Block Chatter**: The Mermaid block MUST start immediately with the graph type (e.g., `graph TD`). NO titles, NO comments, NO plain text inside the backticks.
       - **Mermaid Golden Rule**: Wrap ALL node labels in double quotes (e.g., `A["Label"]`).
       - **Nested Content (ZERO TOLERANCE)**: NEVER use quotes (`"` or `'`), backticks (`` ` ``), parentheses `()`, or brackets `[]` inside a Mermaid label. Use plain alphabetic text only.
       - **Arrows**: Use standard lowercase arrows: `-->`, `---`, `-.-`, `==>`, `--x`, `--o`.
       - **Complexity**: Keep diagrams focused (max 8 nodes).
    6. **Tone**: Rigorous and professional.
    7. **Images**: Can use relevent Images. The image should be complelety relevent to the chapter nd content.
    """
    
    response = client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            temperature=0.4,
        ),
    )
    
    return response.text


def generate_assessment(module_title: str, track_title: str) -> list:
    """
    Generates a dynamic quiz for the end of a module.
    AI decides the number of questions (3-10) and the types (mcq, boolean, multi_select).
    """
    if not client:
        return []
        
    prompt = f"""
    You are an elite technical examiner. Create a rigorous, high-stakes assessment for:
    Track: {track_title}
    Module: {module_title}
    
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
        return json.loads(response.text)
    except Exception as e:
        print(f"Error parsing dynamic assessment JSON: {e}")
        return []


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
