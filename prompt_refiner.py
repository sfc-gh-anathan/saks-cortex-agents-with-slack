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
import requests
import tempfile
import io

# Import charting functions from the new file
from chart_utils import select_and_plot_chart, upload_chart_to_slack


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
SEMANTIC_MODEL = os.getenv("SEMANTIC_MODEL") # CORRECTED: Typo fixed here
SEARCH_SERVICE = os.getenv("SEARCH_SERVICE")
RSA_PRIVATE_KEY_PATH = os.getenv("RSA_PRIVATE_KEY_PATH")
MODEL = os.getenv("MODEL")

# --- Environment Variable Validation (Added for Robustness) ---
required_env_vars = ["ACCOUNT", "HOST", "DEMO_USER", "DEMO_DATABASE", "DEMO_SCHEMA", "DEMO_USER_ROLE", "WAREHOUSE", "SLACK_APP_TOKEN", "SLACK_BOT_TOKEN", "AGENT_ENDPOINT", "SEMANTIC_MODEL", "SEARCH_SERVICE", "RSA_PRIVATE_KEY_PATH", "MODEL"]
for var in required_env_vars:
    if not os.getenv(var):
        print(f"Error: Required environment variable '{var}' is not set. Please check your .env file.")
        exit(1) # Exit if essential environment variables are missing

DEBUG = False # Set to True for more verbose console output to see debug prints

# --- Initializes Slack App ---
app = App(token=SLACK_BOT_TOKEN)

# --- Global In-Memory Cache for SQL Queries ---
# WARNING: In a production environment, this should be replaced with a more robust,
# persistent, and thread-safe caching mechanism (e.g., Redis, database)
# to handle multiple concurrent users and bot restarts.
global_sql_cache = {}
SQL_SHOW_BUTTON_ACTION_ID = "show_full_sql_query_button"
REFINE_QUERY_BUTTON_ACTION_ID = "refine_query_button"
RENDER_CHART_BUTTON_ACTION_ID = "render_chart_button"
DOWNLOAD_DATA_BUTTON_ACTION_ID = "download_data_button"

# Global variable to store the last user prompt
last_user_prompt_global = ""

# Constants for Snowflake stored procedure parameters
SNOWFLAKE_STAGE_PATH = '@"SLACK_DEMO"."SLACK_SCHEMA"."SLACK_SEMANTIC_MODELS"'
SNOWFLAKE_FILE_NAME = 'retail_sales_data.yaml'


# --- Slack Message Handlers ---

@app.event("message")
def handle_message_events(ack, body, say):
    global last_user_prompt_global
    try:
        ack()
        prompt = body['event']['text']
        last_user_prompt_global = prompt
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
                        "text": "❄️ Snowflake Cortex AI is generating a response. Please wait...", # Unicode Emoji
                    }
                },
                {
                    "type": "divider"
                },
            ]
        )
        response = ask_agent(prompt)
        display_agent_response(response, say, app.client, body)
    except Exception as e:
        error_info = f"{type(e).__name__} at line {e.__traceback__.tb_lineno} of {__file__}: {e}"
        print(f"ERROR: {error_info}")
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

# --- Helper for SQL display blocks ---
def get_sql_code_block(sql_query):
    """
    Generates Slack rich_text block for displaying a SQL query as code.
    """
    return {
        "type": "rich_text",
        "elements": [
            {
                "type": "rich_text_section",
                "elements": [
                    {
                        "type": "text",
                        "text": "SQL Query:",
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
                        "text": sql_query
                    }
                ]
            }
        ]
    }

# Helper for Refine Query button element
def get_refine_query_button_element():
    """
    Returns the Slack Block Kit element for the "Refine Prompt" button.
    """
    return {
        "type": "button",
        "text": {
            "type": "plain_text",
            "text": "Refine Prompt",
            "emoji": True
        },
        "style": "primary",
        "action_id": REFINE_QUERY_BUTTON_ACTION_ID
    }

# Helper for Show SQL Query button element
def get_show_sql_query_button_element():
    """
    Returns the Slack Block Kit element for the "Show SQL Query" button.
    """
    return {
        "type": "button",
        "text": {
            "type": "plain_text",
            "text": "Show SQL Query",
            "emoji": True
        },
        # MODIFIED: Removed style property to allow default (white) color
        "action_id": SQL_SHOW_BUTTON_ACTION_ID
    }

# Helper for Render Chart button element
def get_render_chart_button_element():
    """
    Returns the Slack Block Kit element for the "Render Chart" button.
    """
    return {
        "type": "button",
        "text": {
            "type": "plain_text",
            "text": "Render Chart",
            "emoji": True
        },
        "style": "primary",
        "action_id": RENDER_CHART_BUTTON_ACTION_ID
    }

# NEW: Helper for Download Data button element
def get_download_data_button_element():
    """
    Returns the Slack Block Kit element for the "Download Data" button.
    """
    return {
        "type": "button",
        "text": {
            "type": "plain_text",
            "text": "Download Data",
            "emoji": True
        },
        "style": "primary",
        "action_id": DOWNLOAD_DATA_BUTTON_ACTION_ID
    }

# NEW: Combined actions block for all four buttons
def get_action_buttons_block(include_show_sql=True): # MODIFIED: Added include_show_sql parameter
    """
    Returns a Slack Block Kit 'actions' block containing desired buttons on the same row.
    """
    elements = []
    if include_show_sql: # Only add if requested
        elements.append(get_show_sql_query_button_element())

    elements.extend([
        get_refine_query_button_element(),
        get_render_chart_button_element(),
        get_download_data_button_element()
    ])

    return {
        "type": "actions",
        "elements": elements
    }

# --- Response Display and Charting Logic ---

def display_agent_response(content, say, app_client, original_body):
    """
    Displays the agent's response, handling both SQL results (with charts)
    and unstructured text responses.
    """
    channel_id = original_body['event']['channel']

    final_blocks = []

    if content['sql']:
        sql = content['sql']

        df = pd.read_sql(sql, CONN)

        if DEBUG:
            print("Original DataFrame info:")
            df.info()

        # --- Robust Type Conversion for Plotting ---
        if len(df.columns) >= 2:
            try:
                if pd.api.types.is_object_dtype(df.iloc[:, 0]) or pd.api.types.is_string_dtype(df.iloc[:, 0]):
                    temp_col = pd.to_datetime(df.iloc[:, 0], errors='coerce')
                    if not temp_col.isna().all():
                        df[df.columns[0]] = temp_col
                        if DEBUG:
                            print(f"Converted column '{df.columns[0]}' to datetime where possible.")
            except Exception as e:
                if DEBUG:
                    print(f"Could not convert column '{df.columns[0]}' to datetime: {e}")

            for i in range(len(df.columns)):
                try:
                    if pd.api.types.is_object_dtype(df.iloc[:, i]) or pd.api.types.is_string_dtype(df.iloc[:, i]):
                        temp_col = pd.to_numeric(df.iloc[:, i], errors='coerce')
                        if not temp_col.isna().all() and (temp_col.notna().sum() / len(temp_col) > 0.5):
                            df[df.columns[i]] = temp_col
                            if DEBUG:
                                print(f"Converted column '{df.columns[i]}' to numeric where possible.")
                    elif pd.api.types.is_numeric_dtype(df.iloc[:, i]):
                        df[df.columns[i]] = df[df.columns[i]].astype(float)
                except Exception as e:
                    if DEBUG:
                        print(f"Could not convert column '{df.columns[i]}' to numeric: {e}")

        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                if df[col].isnull().any():
                    df.dropna(subset=[col], inplace=True)
                    if DEBUG:
                        print(f"Dropped rows with NaN in numeric column '{col}'.")

        if DEBUG:
            print("\nDataFrame after type conversion info:")
            df.info()

            print("\nDataFrame head after conversion:")
            print(df.head())

        # Handle Single-Row Answers Specifically
        if len(df) == 1:
            formatted_answer = ""
            for col in df.columns:
                formatted_answer += f"*{col.replace('_', ' ').title()}*: {df[col].iloc[0]}\n"

            final_blocks.append({
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
            })
        else:
            # Limit displayed rows and indicate truncation
            original_rows = len(df)
            display_df = df.head(10)
            truncated_message = ""
            if original_rows > 10:
                truncated_message = "\n\n(Results truncated to 10 lines.)"

            # Display DataFrame as Text Table
            final_blocks.append({
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
            })

        # Add the combined action buttons block, including Show SQL Query initially.
        final_blocks.append(get_action_buttons_block(include_show_sql=True)) # Pass True to include Show SQL

        # Send the initial message and capture its timestamp (ts)
        try:
            post_response = app_client.chat_postMessage(
                channel=channel_id,
                blocks=final_blocks,
                text="Your query results are ready."
            )
            message_ts = post_response['ts']

            # Store the full SQL query in the global cache, keyed by message_ts
            global_sql_cache[message_ts] = sql

        except Exception as e:
            print(f"Error posting initial message to Slack: {e}")
            say(f"An error occurred while posting results: {e}")
            return

    else:
        # --- Handle Unstructured Text Responses ---
        text_response_blocks = [
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
            },
            # No buttons are added here as the response is unstructured
        ]

        say(
            text="Answer:",
            blocks=text_response_blocks
        )

# --- Action handler for "Show SQL Query" button ---
@app.action(SQL_SHOW_BUTTON_ACTION_ID)
def handle_show_sql_query(ack, body, client):
    ack()

    message_ts = body['message']['ts']
    channel_id = body['channel']['id']

    # Retrieve the SQL query from the cache using the message's timestamp
    sql_query = global_sql_cache.get(message_ts)

    current_blocks = body['message']['blocks']

    blocks_to_rebuild = []
    sql_already_displayed = False

    for block in current_blocks:
        # Filter out the existing action buttons block
        if block.get("type") == "actions" and any(e.get('action_id') in [REFINE_QUERY_BUTTON_ACTION_ID, SQL_SHOW_BUTTON_ACTION_ID, RENDER_CHART_BUTTON_ACTION_ID, DOWNLOAD_DATA_BUTTON_ACTION_ID] for e in block['elements']):
            # This is our action buttons block, we will re-add a modified version later
            continue
        # Check if the SQL is already in the message (e.g., if button was clicked twice)
        if block.get("type") == "rich_text" and any(el.get("text") == "SQL Query:" for el in block.get("elements", []) if el.get("type") == "rich_text_section"):
            sql_already_displayed = True
            # We don't continue here directly because we might want to keep other blocks before and after SQL
        blocks_to_rebuild.append(block)

    updated_blocks = blocks_to_rebuild[:]

    if sql_query and not sql_already_displayed:
        # Insert the full SQL query blocks
        updated_blocks.append(get_sql_code_block(sql_query))
    elif sql_already_displayed:
        # If SQL was already there, provide ephemeral feedback and don't update the message
        client.chat_postMessage(
            channel=channel_id,
            text="The SQL query is already displayed in the message above.",
            thread_ts=message_ts,
            ephemeral=True
        )
        return

    # Re-add the action buttons, but this time, EXCLUDE the "Show SQL Query" button
    updated_blocks.append(get_action_buttons_block(include_show_sql=False)) # Pass False to exclude Show SQL

    try:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=updated_blocks,
            text="Your query results and SQL."
        )
    except Exception as e:
        print(f"Error updating message with SQL: {e}")
        client.chat_postMessage(
            channel=channel_id,
            text=f"An error occurred while displaying the query: {e}",
            thread_ts=message_ts
        )

# Action handler for "Refine Query" button
@app.action(REFINE_QUERY_BUTTON_ACTION_ID)
def handle_refine_query_button_click(ack, body, client):
    """
    Handles the click event for the "Refine Prompt" button.
    Calls the Snowflake stored procedure REFINE_QUERY with the last user prompt.
    """
    ack()

    message_ts = body['message']['ts']
    channel_id = body['channel']['id']

    if not last_user_prompt_global:
        client.chat_postMessage(
            channel=channel_id,
            text="Sorry, I couldn't retrieve the last prompt to refine. Please try inputing another prompt.",
            thread_ts=message_ts
        )
        return

    try:
        # MODIFIED: Used rich_text blocks for reliable bolding and emoji
        client.chat_postMessage(
            channel=channel_id,
            blocks=[
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": "❄️ ", # Unicode emoji
                                },
                                {
                                    "type": "text",
                                    "text": f"Refining prompt for: '{last_user_prompt_global}'...",
                                    "style": {
                                        "bold": True
                                    }
                                }
                            ]
                        }
                    ]
                }
            ],
            thread_ts=message_ts
        )

        cur = CONN.cursor()

        escaped_stage_path = SNOWFLAKE_STAGE_PATH.replace("'", "''")
        escaped_file_name = SNOWFLAKE_FILE_NAME.replace("'", "''")
        escaped_user_prompt = last_user_prompt_global.replace("'", "''")

        # Using DATABASE and SCHEMA environment variables for consistency
        sql_call_formatted = (
            f"CALL {DATABASE}.{SCHEMA}.REFINE_QUERY("
            f"'{escaped_stage_path}', "
            f"'{escaped_file_name}', "
            f"'{escaped_user_prompt}')"
        )

        if DEBUG:
            print(f"DEBUG: Attempting to call with formatted SQL: {sql_call_formatted}")

        cur.execute(sql_call_formatted)

        result = cur.fetchone()

        if result:
            refinement_message = result[0]
        else:
            refinement_message = "No refinement suggestions received from Cortex."

        client.chat_postMessage(
            channel=channel_id,
            text=f"Prompt Refinement: {refinement_message}",
            thread_ts=message_ts
        )

    except Exception as e:
        error_info = f"{type(e).__name__} at line {e.__traceback__.tb_lineno} of {__file__}: {e}"
        print(f"ERROR calling Snowflake REFINE_QUERY: {error_info}")
        client.chat_postMessage(
            channel=channel_id,
            text=f"An error occurred while trying to refine the prompt: {e}",
            thread_ts=message_ts
        )
    finally:
        if 'cur' in locals() and cur:
            cur.close()

# Action handler for "Render Chart" button
@app.action(RENDER_CHART_BUTTON_ACTION_ID)
def handle_render_chart_button_click(ack, body, client):
    ack()
    message_ts = body['message']['ts']
    channel_id = body['channel']['id']

    sql_query = global_sql_cache.get(message_ts)

    if not sql_query:
        client.chat_postMessage(
            channel=channel_id,
            text="Sorry, I couldn't retrieve the data for charting. The query might have expired or been cleared.",
            thread_ts=message_ts
        )
        return

    try:
        # MODIFIED: Used rich_text blocks for reliable bolding and emoji
        client.chat_postMessage(
            channel=channel_id,
            blocks=[
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": "📈 ", # MODIFIED: Unicode emoji
                                },
                                {
                                    "type": "text",
                                    "text": "Generating your chart...",
                                    "style": {
                                        "bold": True
                                    }
                                }
                            ]
                        }
                    ]
                }
            ],
            thread_ts=message_ts
        )

        # Re-execute the SQL query to get the data for charting
        df = pd.read_sql(sql_query, CONN)

        if DEBUG:
            print("DataFrame for charting info:")
            df.info()
            print(df.head())

        # --- Robust Type Conversion for Plotting (similar to display_agent_response) ---
        if len(df.columns) >= 2:
            try:
                if pd.api.types.is_object_dtype(df.iloc[:, 0]) or pd.api.types.is_string_dtype(df.iloc[:, 0]):
                    temp_col = pd.to_datetime(df.iloc[:, 0], errors='coerce')
                    if not temp_col.isna().all():
                        df[df.columns[0]] = temp_col
                        if DEBUG:
                            print(f"Chart: Converted column '{df.columns[0]}' to datetime.")
            except Exception as e:
                if DEBUG:
                    print(f"Chart: Could not convert column '{df.columns[0]}' to datetime: {e}")

            for i in range(len(df.columns)):
                try:
                    if pd.api.types.is_object_dtype(df.iloc[:, i]) or pd.api.types.is_string_dtype(df.iloc[:, i]):
                        temp_col = pd.to_numeric(df.iloc[:, i], errors='coerce')
                        if not temp_col.isna().all() and (temp_col.notna().sum() / len(temp_col) > 0.5):
                            df[df.columns[i]] = temp_col
                            if DEBUG:
                                print(f"Chart: Converted column '{df.columns[i]}' to numeric.")
                    elif pd.api.types.is_numeric_dtype(df.iloc[:, i]):
                        df[df.columns[i]] = df[df.columns[i]].astype(float)
                except Exception as e:
                    if DEBUG:
                        print(f"Chart: Could not convert column '{df.columns[i]}' to numeric: {e}")

        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                if df[col].isnull().any():
                    df.dropna(subset=[col], inplace=True)
                    if DEBUG:
                        print(f"Chart: Dropped rows with NaN in numeric column '{col}'.")


        chart_img_url = select_and_plot_chart(df, client)
        if chart_img_url:
            client.chat_postMessage(
                channel=channel_id,
                blocks=[
                    {
                        "type": "image",
                        "title": {
                            "type": "plain_text",
                            "text": "Generated Chart"
                        },
                        "image_url": chart_img_url,
                        "alt_text": "Generated Chart"
                    }
                ],
                thread_ts=message_ts
            )
        else:
            client.chat_postMessage(
                channel=channel_id,
                text="I couldn't generate a suitable chart for the data returned by the query. Please check the data format.",
                thread_ts=message_ts
            )

    except Exception as e:
        error_info = f"{type(e).__name__} at line {e.__traceback__.tb_lineno} of {__file__}: {e}"
        print(f"ERROR rendering chart: {error_info}")
        client.chat_postMessage(
            channel=channel_id,
            text=f"An error occurred while trying to render the chart: {e}",
            thread_ts=message_ts
        )

# Action handler for "Download Data" button
@app.action(DOWNLOAD_DATA_BUTTON_ACTION_ID)
def handle_download_data_button_click(ack, body, client):
    ack()
    message_ts = body['message']['ts']
    channel_id = body['channel']['id']

    sql_query = global_sql_cache.get(message_ts)

    if not sql_query:
        client.chat_postMessage(
            channel=channel_id,
            text="Sorry, I couldn't retrieve the data for download. The query might have expired or been cleared.",
            thread_ts=message_ts
        )
        return

    try:
        # MODIFIED: Used rich_text blocks for reliable bolding and emoji
        client.chat_postMessage(
            channel=channel_id,
            blocks=[
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [
                                {
                                    "type": "text",
                                    "text": "📥 ", # Unicode emoji
                                },
                                {
                                    "type": "text",
                                    "text": "Preparing data for download...",
                                    "style": {
                                        "bold": True
                                    }
                                }
                            ]
                        }
                    ]
                }
            ],
            thread_ts=message_ts
        )

        # Re-execute the SQL query to get the data
        df = pd.read_sql(sql_query, CONN)

        if DEBUG:
            print(f"DEBUG: DataFrame shape for download: {df.shape}")
            if not df.empty:
                print(f"DEBUG: First few rows of DataFrame for download:\n{df.head().to_string()}")
            else:
                print("DEBUG: DataFrame is empty for download.")

        if df.empty:
            client.chat_postMessage(
                channel=channel_id,
                text="The query returned no data to download.",
                thread_ts=message_ts
            )
            return

        # Use BytesIO to create an in-memory file for CSV
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)

        file_name = f"query_results_{int(time.time())}.csv"

        if DEBUG:
            print(f"DEBUG: Attempting to upload file '{file_name}' to channel '{channel_id}' with thread_ts '{message_ts}'")

        # Capture the response from Slack API for more detailed debugging
        upload_response = client.files_upload_v2(
            channel=channel_id,
            file=csv_buffer.getvalue().encode('utf-8'), # Encode to bytes for upload
            filename=file_name,
            title="Query Results Data",
            thread_ts=message_ts,
            initial_comment=f"Here is the data generated by your query: `{file_name}`"
        )
        if DEBUG:
            print(f"DEBUG: Slack upload response: {upload_response}")
            if upload_response.get('ok'):
                print(f"DEBUG: File uploaded successfully: {upload_response.get('file', {}).get('permalink')}")
            else:
                print(f"DEBUG: File upload failed: {upload_response.get('error')}")


    except Exception as e:
        error_info = f"{type(e).__name__} at line {e.__traceback__.tb_lineno} of {__file__}: {e}"
        print(f"ERROR downloading data: {error_info}")
        client.chat_postMessage(
            channel=channel_id,
            text=f"An error occurred while trying to download the data: {e}",
            thread_ts=message_ts
        )


# --- Initialization and App Start ---

def init():
    """
    Initializes Snowflake connection and Cortex Chat Agent.
    """
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