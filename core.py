import os
from dotenv import load_dotenv
import json
import duckdb
import pandas as pd
from pathlib import Path
from openai import OpenAI

from tools import TOOLBOX, DATASET, load_data
from json_schema import tools_schema
import memory


# =============================================================================
# 1. LOAD YOUR DATASETS HERE  (manual, top level, outside every function)
# =============================================================================
SUPPORTED = {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".json", ".parquet"}

def load_folder(folder: str = "data"):
    for f in sorted(Path(folder).iterdir()):
        if f.suffix.lower() in SUPPORTED:
            print(load_data(str(f)))

load_folder()



load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API"))


def load_usage_guide() -> str:
    """Loads external guidelines from markdown file if it exists."""
    guide_path = "tool_usage_guide.md"
    if os.path.exists(guide_path):
        with open(guide_path, "r", encoding="utf-8") as f:
            return f.read()
    return "No external tool usage guide found."

def system_prompt() -> str:
    loaded_datasets = list(DATASET.keys())
    usage_guide = load_usage_guide()
    memories = memory.format_memory_for_prompt()  # Assuming memory is defined elsewhere

    return f"""You are a rude expert Data Analysis Agent.

            ### LIST OF CURRENTLY LOADED DATASETS:
            {loaded_datasets}

            ### TOOL USAGE GUIDELINES:
            {usage_guide}

            ### PERSISTENT DOMAIN MEMORY & USER PREFERENCES:
            {memories}

            ### RULES:
            1. Always ground your final answers in data returned by tools. Never guess numbers.
            2. Read tool errors carefully and fix your parameters if a tool fails.
            """


def run_agent(prompt: str, convo_history: list, max_steps: int = 8) -> str:
    """ Run the agent loop with one question.
    Uses a scratchpad to keep track of the conversation and tool usage.
    And output 
    """
    system_message = system_prompt()

    # Making the context for the LLM prompt
    input_msg = [
        {"role": "system", "content": system_message},
    ]
    input_msg.extend(convo_history)  # Add previous conversation history
    input_msg.append({"role": "user", "content": prompt})  # Add the new user prompt

    print("\n" + "=" * 55)
    print("🔍 [AGENT STARTED THINKING]")   
    print("=" * 55)

    # Now the LLM will run
    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=input_msg,
            tools=tools_schema,
            temperature=0,
            tool_choice="auto",
            parallel_tool_calls=False
        )

        response_msg = response.choices[0].message
        input_msg.append(response_msg)  # Keep track of history

        # 2. Check: Did the LLM decide to call a tool?
        if response_msg.tool_calls:
            for tool_call in response_msg.tool_calls:
                fn_name = tool_call.function.name
                # Checking if func arg are correct, prone to errors.
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except Exception as e:
                        fn_args = {}
                        raw_result = f"Error: Invalid JSON arguments from model. '{fn_name}': {str(e)}"
                        input_msg.append({
                            "role" : "tool",
                            "tool_call_id" : tool_call.id,
                                        "content" : raw_result
                        })
                        print(f"❌ Argument Parsing Failed: {e}")
                        continue

                # Printing that LLM calling tool
                print(f"\n--- Step {step} ---")
                print(f"🛠️  ACTION: Agent called tool -> `{fn_name}`")
                print(f"📥 ARGUMENTS:\n{json.dumps(fn_args, indent=2)}")

                # Execute the tool
                print("⚙️  EXECUTING...")
                if fn_name not in TOOLBOX:
                    raw_result = f"Error: Tool '{fn_name}' does not exist. Available: {list(TOOLBOX.keys())}"
                else:
                    try:
                        func = TOOLBOX[fn_name]
                        raw_result = func(**fn_args)
                    except Exception as e:
                        raw_result = f"Execution error in '{fn_name}': {str(e)}"

            # Managing to output the raw_result for big results to display in terminal
            if len(str(raw_result)) > 500:
                print(f"📤 TOOL OUTPUT: (truncated to 500 chars)\n{str(raw_result)[:500]}...")
            else:
                print(f"📤 TOOL OUTPUT:\n{raw_result}")
            print("-" * 55)

            # 3. Message List appendment
            input_msg.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(raw_result)[:8000]  # Limit to 5000 chars for LLM context
            })

        # Tool use END
        else:
            # 5. Final loop ends
            final_answer = response_msg.content

            print("\n[THINKING ENDS]")
            print("=" * 55)
            return str(final_answer)
            

    print("⚠️ [AGENT STOPPED: Reached maximum step limit]")
    print("=" * 55)
    return "The agent reached the maximum step limit without arriving at a final answer."


def chat():
    print("=" * 60)
    print("🤖 Tabular Data Analysis Agent Ready")
    print("=" * 60)
 
    # Show what was loaded at the top of this file
    print("\n📂 LOADED DATASETS:")
    print(list(DATASET.keys()))
 
    saved = memory.format_memory_for_prompt()
    if saved != "None.":
        print("\n🧠 REMEMBERED FROM EARLIER SESSIONS:")
        print(saved)
 

    # CONTEXT SHRINKAGE:

    conversation_history = []
 
    while True:
        user_input = input("\nYou: ").strip()
 
        # 1. Run the agent (shows dataset choice + tool steps in real time)
        final_answer = run_agent(prompt=user_input, convo_history=conversation_history)
 
        # 2. Print the final answer to the user
        print(f"\nAgent:\n{final_answer}")
 
        # 3. Auto-extract domain memory and save it to agent_memory.json
        memory.auto_extract_and_save(user_input, final_answer, client)
 
        # 4. Append ONLY the clean dialogue to history
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": final_answer})
 
        # 5. Ask to continue, or exit
        cont = input("\nContinue chatting? (y/n): ").strip().lower()
        if cont != "y":
            print("Session ended. See you next time!")
            break
 
 
if __name__ == "__main__":
    chat()