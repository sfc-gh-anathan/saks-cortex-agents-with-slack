import os
from dotenv import load_dotenv
from dotenv import find_dotenv # Make sure to import find_dotenv

# --- Start of Debugging ---
print("--- Starting debug ---")

# 1. See if the library can find the file
dotenv_path = find_dotenv()
if dotenv_path:
    print(f"✅ Found .env file at: {dotenv_path}")
else:
    print("❌ Could not find a .env file. Make sure it's in the same directory you are running the script from.")

# 2. See if the library loads the file
load_dotenv(dotenv_path) # Explicitly load from the path we found

# 3. See what values the script is actually getting
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

# The single quotes are important here to show any hidden spaces
print(f"Value of SLACK_BOT_TOKEN is: '{SLACK_BOT_TOKEN}'")
print(f"Value of SLACK_APP_TOKEN is: '{SLACK_APP_TOKEN}'")
print("--- End of debug ---")
# --- End of Debugging ---


# Your original code (no changes needed below this line)
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

if not SLACK_BOT_TOKEN:
    raise ValueError("Error: SLACK_BOT_TOKEN not found or is empty.")
if not SLACK_APP_TOKEN:
    raise ValueError("Error: SLACK_APP_TOKEN not found or is empty.")

app = App(token=SLACK_BOT_TOKEN)

@app.message("hello")
def message_hello(message, say):
    say(f"Hey there <@{message['user']}>!")

if __name__ == "__main__":
    SocketModeHandler(app, SLACK_APP_TOKEN).start()