import logging
import requests
import json
import uuid
import re
from datetime import datetime, timedelta, timezone
import azure.functions as func

# API endpoints remain the same
BASE_URL = "https://news-agent.codeshare.live"

# --- HELPER FUNCTION TO PARSE DATES ---
def parse_date(date_string: str) -> str:
    """
    Parses various date string formats and returns a standard ISO 8601 date string.
    If a date cannot be parsed, it returns the current UTC date.
    """
    current_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    if not isinstance(date_string, str):
        return current_date_str

    date_string = date_string.strip()
    now = datetime.now(timezone.utc)

    # Handle relative dates like "6h ago", "10h ago"
    if 'ago' in date_string:
        try:
            parts = date_string.split()
            value = int(re.search(r'\d+', parts[0]).group())
            unit = parts[1][0].lower()
            
            if unit == 'h':
                delta = timedelta(hours=value)
            elif unit == 'd':
                delta = timedelta(days=value)
            elif unit == 'm':
                delta = timedelta(minutes=value)
            else:
                return current_date_str
            
            past_date = now - delta
            return past_date.strftime('%Y-%m-%d')
        except (ValueError, IndexError, AttributeError):
            return current_date_str # Return current date if parsing fails

    # Handle partial dates like "Aug 6" by adding the current year
    try:
        # Check if it's in a format like "Mon Day"
        parsed_date = datetime.strptime(f"{date_string} {now.year}", "%b %d %Y")
        return parsed_date.strftime('%Y-%m-%d')
    except ValueError:
        pass # Continue to the next check

    # Handle full date strings
    try:
        parsed_date = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
        return parsed_date.strftime('%Y-%m-%d')
    except ValueError:
        pass # Continue to the next check

    # If all else fails, it's a non-date string like "Varies", "N/A", etc.
    return current_date_str

# --- YOUR EXISTING FUNCTIONS (No changes needed here) ---
def create_session(user_id=None):
    if user_id is None: user_id = str(uuid.uuid4())
    url = f"{BASE_URL}/apps/news_agent/users/{user_id}/sessions"
    headers = {'accept': 'application/json', 'Content-Type': 'application/json'}
    payload = {"additionalProp1": {}}
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()

def run_conversation(session_id, user_id=None, message="Latest news on Electric Vehicles"):
    url = f"{BASE_URL}/run"
    headers = {'accept': 'application/json', 'Content-Type': 'application/json'}
    payload = {"appName": "news_agent", "userId": user_id, "sessionId": session_id, "newMessage": {"parts": [{"text": message}], "role": "user"}, "streaming": False}
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()

def extract_news_content(response):
    """
    Parses the response from the conversational agent.
    This version is robust and handles conversational text and markdown wrappers.
    """
    logging.info("Attempting to parse raw agent response.")
    raw_content = None
    try:
        if not isinstance(response, list) or not response: return None
        first_message = response[0]
        raw_content = first_message['content']['parts'][0]['text']

        # Find the start of the JSON object (the first '{')
        json_start_index = raw_content.find('{')
        # Find the end of the JSON object (the last '}')
        json_end_index = raw_content.rfind('}')

        if json_start_index == -1 or json_end_index == -1:
            logging.error("No JSON object found in the response.")
            return None

        # Slice the string to get only the content between the first and last brace
        json_string = raw_content[json_start_index : json_end_index + 1]
        
        # Fix any missing commas between objects
        fixed_json_string = re.sub(r'}\s*{', '}, {', json_string)
        news_data = json.loads(fixed_json_string)
        return news_data
        
    except Exception as e:
        logging.error(f"Error parsing response: {e}")
        if raw_content: logging.error(f"Raw content that failed parsing: {raw_content}")
        return None

def main(req: func.HttpRequest) -> func.HttpResponse:
    # This main function logic remains the same
    logging.info('Python HTTP trigger function processed a request to fetch and clean news.')
    try:
        user_id = str(uuid.uuid4())
        session_response = create_session(user_id)
        session_id = session_response.get('id')
        if session_id:
            conversation_response = run_conversation(session_id, user_id)
            news_data = extract_news_content(conversation_response)
            if news_data and 'news' in news_data:
                for article in news_data['news']:
                    article['date'] = parse_date(article.get('date'))
                return func.HttpResponse(
                    body=json.dumps(news_data, indent=2),
                    status_code=200,
                    mimetype="application/json"
                )
            else:
                return func.HttpResponse("Failed to parse news data from response", status_code=500)
        else:
            return func.HttpResponse("Failed to get session ID from response", status_code=500)
    except Exception as e:
        logging.error(f"An unexpected error occurred in main function: {e}", exc_info=True)
        return func.HttpResponse(f"An unexpected error occurred: {e}", status_code=500)
