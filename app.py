from typing import Any
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import snowflake.connector
import pandas as pd
from snowflake.core import Root
import generate_jwt
from dotenv import load_dotenv
import matplotlib
import matplotlib.pyplot as plt 
from snowflake.snowpark import Session
import numpy as np
import cortex_chat

matplotlib.use('Agg')
load_dotenv()

ACCOUNT = os.getenv("ACCOUNT")
HOST = os.getenv("HOST")
USER = os.getenv("DEMO_USER")
JWT_USER = os.getenv("JWT_USER")
DATABASE = os.getenv("DEMO_DATABASE")
SCHEMA = os.getenv("DEMO_SCHEMA")
PASSWORD = os.getenv("DEMO_USER_PASSWORD")
ROLE = os.getenv("DEMO_USER_ROLE")
WAREHOUSE = os.getenv("WAREHOUSE")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
AGENT_ENDPOINT = os.getenv("AGENT_ENDPOINT")
SEMANTIC_MODEL = os.getenv("SEMANTIC_MODEL")
SEARCH_SERVICE = os.getenv("SEARCH_SERVICE")
RSA_PRIVATE_KEY_PATH = os.getenv("RSA_PRIVATE_KEY_PATH")
MODEL = os.getenv("MODEL")

# Initializes app
app = App(token=SLACK_BOT_TOKEN)
messages = []

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
                    "text": f":dash_board: Let's BUILD!",
                }
            },
        ]                
    )

@app.event("message")
def handle_message_events(ack, body, say):
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
                    "text": ":dash_board: Snowflake Cortex AI is generating a response. Please wait...",
                }
            },
            {
                "type": "divider"
            },
        ]
    )
    process_prompt(prompt,say)

def process_prompt(prompt,say):
    response = query_agent_api(prompt)
    display_content(response,say)

def say_question(say,prompt):
    say(
        text = "Question:",
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Question: {prompt}",
                }
            },
        ]                
    )
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
                    "text": ":dash_board: Snowflake Cortex AI is generating a response. Please wait...",
                }
            },
            {
                "type": "divider"
            },
        ]
    )

def query_agent_api(prompt):
    resp = CORTEX_APP.chat(prompt)
    return resp

def display_content(content,say):
    if content['sql']:
        sql = content['sql']
        df = pd.read_sql(sql, CONN)
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
                                    "text": f"{df.to_string()}"
                                }
                            ]
                        }
                    ]
                }
            ]
        )
    else:
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

def init():
    conn,jwt,cortex_app = None,None,None

    conn = snowflake.connector.connect(
        user=USER,
        password=PASSWORD,
        account=ACCOUNT,
        warehouse=WAREHOUSE,
        role=ROLE,
        host=HOST
    )
    if not conn.rest.token:
        print(">>>>>>>>>> Snowflake connection unsuccessful!")

    cortex_app = cortex_chat.CortexChat(
        AGENT_ENDPOINT, 
        SEARCH_SERVICE,
        SEMANTIC_MODEL,
        MODEL, 
        generate_jwt.JWTGenerator(ACCOUNT,JWT_USER,RSA_PRIVATE_KEY_PATH).get_token())

    print(">>>>>>>>>> Init complete")
    return conn,jwt,cortex_app

# Start app
if __name__ == "__main__":
    CONN,JWT,CORTEX_APP = init()
    Root = Root(CONN)
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
