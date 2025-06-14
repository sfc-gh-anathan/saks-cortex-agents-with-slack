from typing import Any
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import snowflake.connector
import pandas as pd
from snowflake.core import Root
from dotenv import load_dotenv
import cortex_chat
import time
import requests # Still needed for initial Slack API interaction in upload_chart_to_slack if it remains here

# Import charting functions from the new file
from chart_utils import select_and_plot_chart, upload_chart_to_slack # We will modify upload_chart_to_slack to be passed app.client


# Set Matplotlib backend for server-side generation (can be removed if charting.py handles all plotting)
# import matplotlib
# matplotlib.use('Agg') # Moving this to charting.py

load_dotenv()

# --- Environment Variables ---
ACCOUNT = os.getenv("ACCOUNT")
HOST = os.getenv("HOST")
USER = os.getenv("DEMO_USER")
DATABASE = os.getenv("DEMO_DATABASE")
SCHEMA = os.getenv("DEMO_SCHEMA")
ROLE = os.getenv("DEMO_USER_ROLE")
WAREHOUSE = os.getenv("WAREHOUSE")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
AGENT_ENDPOINT = os.getenv("AGENT_ENDPOINT")
SEMANTIC_MODEL = os.getenv("SEMANTIC_MODEL")
SEARCH_SERVICE = os.getenv("SEARCH_SERVICE")
RSA_PRIVATE_KEY_PATH = os.getenv("RSA_PRIVATE_KEY_PATH")
MODEL = os.getenv("MODEL")

# --- Environment Variable Validation (Added for Robustness) ---
required_env_vars = ["ACCOUNT", "HOST", "DEMO_USER", "DEMO_DATABASE", "DEMO_SCHEMA", "DEMO_USER_ROLE", "WAREHOUSE", "SLACK_APP_TOKEN", "SLACK_BOT_TOKEN", "AGENT_ENDPOINT", "SEMANTIC_MODEL", "SEARCH_SERVICE", "RSA_PRIVATE_KEY_PATH", "MODEL"]
for var in required_env_vars:
    if not os.getenv(var):
        print(f"Error: Required environment variable '{var}' is not set. Please check your .env file.")
        exit(1) # Exit if essential environment variables are missing

DEBUG = False # Set to True for more verbose console output

# --- Initializes Slack App ---
app = App(token=SLACK_BOT_TOKEN)

# --- Slack Message Handlers ---

@app.message("hello")
def message_hello(message, say):
    build = """
Not a developer was stirring, all deep in the fight.
The code was deployed in the pipelines with care,
In hopes that the features would soon be there.

And execs, so eager to see the results,
Were prepping their speeches, avoiding the gulps.
When, what to my wondering eyes should appear,
But a slide-deck update, with a demo so clear!

And we shouted out to developers,
Let’s launch this build live and avoid any crash!
The demos they created, the videos they made,
Were polished and ready, the hype never delayed.
            """

    say(build)
    say(
        text = "Let's BUILD",
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f":snowflake: Let's BUILD!",
                }
            },
        ]
    )

@app.event("message")
def handle_message_events(ack, body, say):
    try:
        ack()
        prompt = body['event']['text']
        say(
            text = "Snowflake Cortex AI is generating a response",
            blocks=[
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "plain_text",
                        "text": ":snowflake: Snowflake Cortex AI is generating a response. Please wait...",
                    }
                },
                {
                    "type": "divider"
                },
            ]
        )
        response = ask_agent(prompt)
        display_agent_response(response, say, app.client) # Pass app.client to display_agent_response
    except Exception as e:
        error_info = f"{type(e).__name__} at line {e.__traceback__.tb_lineno} of {__file__}: {e}"
        print(f"ERROR: {error_info}") # Use a clear ERROR prefix for logs
        say(
            text = "Request failed...",
            blocks=[
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "plain_text",
                        "text": f"An unexpected error occurred: {type(e).__name__}. Please try again later or contact support if the issue persists.",
                    }
                },
                {
                    "type": "divider"
                },
            ]
        )

# --- Agent Interaction ---

def ask_agent(prompt):
    """
    Sends the user prompt to the Cortex Chat Agent.
    """
    resp = CORTEX_APP.chat(prompt)
    return resp

# --- Response Display and Charting Logic ---

def display_agent_response(content, say, app_client): # Added app_client parameter
    """
    Displays the agent's response, handling both SQL results (with charts)
    and unstructured text responses.
    """
    if content['sql']:
        sql = content['sql']

        # --- Display SQL Code ---
        say(
            text = "Here's the SQL query:",
            blocks=[
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": "Here's the SQL query:",
                                    "style": {
                                        "bold": True
                                    }
                                }
                            ]
                        },
                        {
                            "type": "rich_text_preformatted",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": sql
                                }
                            ]
                        }
                    ]
                }
            ]
        )
        # --- End Display SQL Code ---

        df = pd.read_sql(sql, CONN)

        if DEBUG:
            print("Original DataFrame info:")
            df.info() # Debugging: Print DataFrame info to check dtypes

        # --- Robust Type Conversion for Plotting ---
        # Attempt to convert relevant columns to expected types before charting logic
        if len(df.columns) >= 2:
            try:
                # Try to convert the first column to datetime if it's an object/string
                if pd.api.types.is_object_dtype(df.iloc[:, 0]) or pd.api.types.is_string_dtype(df.iloc[:, 0]):
                    temp_col = pd.to_datetime(df.iloc[:, 0], errors='coerce')
                    if not temp_col.isna().all(): # Only convert if some values are valid datetimes
                        df[df.columns[0]] = temp_col
                        if DEBUG:
                            print(f"Converted column '{df.columns[0]}' to datetime where possible.")
            except Exception as e:
                if DEBUG:
                    print(f"Could not convert column '{df.columns[0]}' to datetime: {e}")
            
            # Iterate through all columns to convert to numeric if appropriate
            for i in range(len(df.columns)):
                try:
                    if pd.api.types.is_object_dtype(df.iloc[:, i]) or pd.api.types.is_string_dtype(df.iloc[:, i]):
                        temp_col = pd.to_numeric(df.iloc[:, i], errors='coerce')
                        # Convert if mostly numeric and not entirely NaN after coercion
                        if not temp_col.isna().all() and (temp_col.notna().sum() / len(temp_col) > 0.5):
                            df[df.columns[i]] = temp_col
                            if DEBUG:
                                print(f"Converted column '{df.columns[i]}' to numeric where possible.")
                    elif pd.api.types.is_numeric_dtype(df.iloc[:, i]):
                        # Ensure standard float type for plotting consistency
                        df[df.columns[i]] = df[df.columns[i]].astype(float)
                except Exception as e:
                    if DEBUG:
                        print(f"Could not convert column '{df.columns[i]}' to numeric: {e}")
        
        # --- Drop rows with NaN in numeric columns after conversion ---
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                if df[col].isnull().any():
                    df.dropna(subset=[col], inplace=True)
                    if DEBUG:
                        print(f"Dropped rows with NaN in numeric column '{col}'.")

        if DEBUG:
            print("\nDataFrame after type conversion info:")
            df.info() # Debugging: Print DataFrame info after conversion

            print("\nDataFrame head after conversion:")
            print(df.head()) # Debugging: Print head to see actual values and types

        # --- Handle Single-Row Answers Specifically ---
        if len(df) == 1:
            formatted_answer = ""
            for col in df.columns:
                formatted_answer += f"*{col.replace('_', ' ').title()}*: {df[col].iloc[0]}\n"
            
            say(
                text = "Here's the specific information you requested:",
                blocks=[
                    {
                        "type": "rich_text",
                        "elements": [
                            {
                                "type": "rich_text_section",
                                "elements": [
                                    {
                                        "type": "text",
                                        "text": "Here's the specific information you requested:",
                                        "style": {
                                            "bold": True
                                        }
                                    }
                                ]
                            },
                            {
                                "type": "rich_text_preformatted",
                                "elements": [
                                    {
                                        "type": "text",
                                        "text": formatted_answer
                                    }
                                ]
                            }
                        ]
                    }
                ]
            )
            if DEBUG:
                print("Displayed single-row answer as formatted text.")
            return # Exit function as no chart is needed

        # --- Limit displayed rows and indicate truncation ---
        original_rows = len(df)
        display_df = df.head(10) # Limit to first 10 rows for display
        truncated_message = ""
        if original_rows > 10:
            truncated_message = "\n\n(Results truncated to 10 lines.)"

        # --- Display DataFrame as Text Table (if not single row) ---
        say(
            text = "Answer:",
            blocks=[
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_quote",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": "Answer:",
                                    "style": {
                                        "bold": True
                                    }
                                }
                            ]
                        },
                        {
                            "type": "rich_text_preformatted",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": f"{display_df.to_string()}{truncated_message}"
                                }
                            ]
                        }
                    ]
                }
            ]
        )

        # --- Dynamic Chart Selection Logic ---
        chart_img_url = select_and_plot_chart(df, app_client) # Pass app_client to charting function
        if chart_img_url is not None:
            say(
                text = "Chart",
                blocks=[
                    {
                        "type": "image",
                        "title": {
                            "type": "plain_text",
                            "text": "Chart"
                        },
                        "block_id": "image",
                        "slack_file": {
                            "url": f"{chart_img_url}"
                        },
                        "alt_text": "Chart"
                    }
                ]
            )
        else:
            if DEBUG:
                print("No suitable chart could be generated for this data.")
            say(
                text = "No chart could be generated for this data.",
                blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "plain_text",
                            "text": "Note: No chart could be generated for this data due to its format.",
                        }
                    }
                ]
            )
    else:
        # --- Handle Unstructured Text Responses ---
        say(
            text = "Answer:",
            blocks = [
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_quote",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": f"Answer: {content['text']}",
                                    "style": {
                                        "bold": True
                                    }
                                }
                            ]
                        },
                        {
                            "type": "rich_text_quote",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": f"* Citation: {content['citations']}",
                                    "style": {
                                        "italic": True
                                    }
                                }
                            ]
                        }
                    ]
                }
            ]
        )

# --- Initialization and App Start ---

def init():
    """
    Initializes Snowflake connection and Cortex Chat Agent.
    """
    # Removed unused 'jwt' variable
    conn, cortex_app = None, None

    try:
        conn = snowflake.connector.connect(
            user=USER,
            authenticator="SNOWFLAKE_JWT",
            private_key_file=RSA_PRIVATE_KEY_PATH,
            account=ACCOUNT,
            warehouse=WAREHOUSE,
            role=ROLE,
            host=HOST
        )
        if not conn.rest.token:
            raise Exception("Snowflake connection unsuccessful: No token received.")
        print(">>>>>>>>>> Snowflake connection successful.")
    except Exception as e:
        print(f"ERROR: Failed to connect to Snowflake: {e}")
        exit(1) # Exit if Snowflake connection fails

    try:
        cortex_app = cortex_chat.CortexChat(
            AGENT_ENDPOINT,
            SEARCH_SERVICE,
            SEMANTIC_MODEL,
            MODEL,
            ACCOUNT,
            USER,
            RSA_PRIVATE_KEY_PATH
        )
        print(">>>>>>>>>> Cortex Chat Agent initialized.")
    except Exception as e:
        print(f"ERROR: Failed to initialize Cortex Chat Agent: {e}")
        exit(1) # Exit if Cortex Chat Agent initialization fails

    print(">>>>>>>>>> Init complete")
    return conn, cortex_app

if __name__ == "__main__":
    CONN, CORTEX_APP = init()
    Root = Root(CONN) # Assuming Root is used elsewhere or for Snowpark Session
    print("Starting SocketModeHandler...")
    SocketModeHandler(app, SLACK_APP_TOKEN).start()