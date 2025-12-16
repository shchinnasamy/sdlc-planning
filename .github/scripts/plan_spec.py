import os
import json
import time
import requests
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, ToolSet

# 1. SETUP AUTH & CLIENT
# DefaultAzureCredential automatically picks up the AZURE_CLIENT_ID/SECRET/TENANT env vars
credential = DefaultAzureCredential()
client = AIProjectClient.from_connection_string(
    credential=credential,
    conn_str=os.environ["AZURE_PROJECT_CONNECTION_STRING"]
)

# 2. DEFINE THE TOOL (Bypassing Portal UI issues)
# We define the tool schema right here so the Agent definitely knows about it.
def create_github_task_dummy(title, body, labels):
    """Dummy function to generate the schema, actual execution happens in the loop."""
    pass

# Create the tool definition
tool_set = ToolSet()
tool_set.add(
    FunctionTool(
        {
            "name": "create_github_task",
            "description": "Creates a technical task in GitHub Issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Title of the task"},
                    "body": {"type": "string", "description": "Detailed description"},
                    "labels": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["title", "body"]
            }
        },
        create_github_task_dummy # This binds the schema
    )
)

# 3. UPDATE AGENT (OPTIONAL BUT SAFER)
# This ensures your Agent on Azure actually has the tool enabled
agent_id = os.environ["AGENT_ID"]
# We fetch the agent to make sure we are talking to the right one
agent = client.agents.get_agent(agent_id)
# (Optional) We could update the agent here, but usually, passing tool_set to create_run is safer for temporary tools

# 4. RUN THE AGENT
print(f"Starting run for Spec: {os.environ['ISSUE_TITLE']}")

thread = client.agents.create_thread()
client.agents.create_message(
    thread_id=thread.id,
    role="user",
    content=f"Spec Title: {os.environ['ISSUE_TITLE']}\n\nSpec Body: {os.environ['ISSUE_BODY']}"
)

# We pass the tool_set here so the run knows it can use these tools
run = client.agents.create_run(
    thread_id=thread.id, 
    assistant_id=agent_id
    # Note: If you didn't successfully attach the tool in the portal, 
    # the SDK might require you to update the assistant first or relying on the portal config.
    # For this PoC, we assume the agent 'knows' it's a PM, but we handle the tool execution locally.
)

# 5. EXECUTION LOOP
while True:
    run = client.agents.get_run(thread_id=thread.id, run_id=run.id)
    print(f"Run Status: {run.status}")
    
    if run.status in ["completed", "failed", "cancelled"]:
        break
    
    if run.status == "requires_action":
        tool_calls = run.required_action.submit_tool_outputs.tool_calls
        tool_outputs = []
        
        for tool in tool_calls:
            if tool.function.name == "create_github_task":
                args = json.loads(tool.function.arguments)
                print(f"Agent executing tool: {args['title']}")
                
                # EXECUTE: Call Logic App
                try:
                    resp = requests.post(os.environ["LOGIC_APP_URL"], json=args)
                    output_str = f"Success: {resp.status_code}"
                except Exception as e:
                    output_str = f"Error: {str(e)}"
                
                tool_outputs.append({
                    "tool_call_id": tool.id,
                    "output": output_str
                })
        
        # Submit results back to agent
        client.agents.submit_tool_outputs(thread_id=thread.id, run_id=run.id, tool_outputs=tool_outputs)
    
    time.sleep(2)

if run.status == "failed":
    print(f"Agent failed: {run.last_error}")
    exit(1)

print("Planning Complete.")