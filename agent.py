import os
from openai import OpenAI

# Initialize the OpenAI client pointing to Experiential Labs API
client = OpenAI(
    base_url="https://api.experientiallabs.ai/v1",
    api_key=os.environ.get("EXPLABS_API_KEY")
)

def generate_code_update(prompt: str) -> str:
    """
    Sends the user request to claude-opus-5-fast and returns the generated response.
    """
    try:
        response = client.chat.completions.create(
            model="claude-opus-5-fast",
            messages=[
                {
                    "role": "system",
                    "content": "You are an AI developer agent. Update HTML/CSS code directly based on user requests."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=0.2
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error calling Experiential Labs API: {e}")
        return None

# Example usage inside your Telegram message handler:
# user_prompt = "Change website background color to red"
# updated_html = generate_code_update(user_prompt)
