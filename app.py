import logging
import os
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from typing import List, Optional, Union, Dict, Any
from neo4j import GraphDatabase
from mem0 import Memory
from dotenv import load_dotenv

# logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


load_dotenv()

app = FastAPI()

openai_api_key = os.getenv("OPENAI_API_KEY")

neo4j_url = os.getenv("NEO4J_URL")
neo4j_username = os.getenv("NEO4J_USERNAME")
neo4j_password = os.getenv("NEO4J_PASSWORD")

qdrant_url = os.getenv("QDRANT_URL")
qdrant_api_key = os.getenv("QDRANT_API_KEY")


config = {
    "graph_store": {
        "provider": "neo4j",
        "config": {
            "url": neo4j_url,        
            "username": neo4j_username, 
            "password": neo4j_password 
        }
    },
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "url": "https://0a58b489-5983-4e97-a5fc-cd84e352c997.us-east4-0.gcp.cloud.qdrant.io:6333",
            "api_key": qdrant_api_key
        }
    },
    "version": "v1.1"
}

m = Memory.from_config(config_dict=config)

# Secret key for authentication
SECRET_KEY = "XQNlX3oy2rQzZKoBBAILdoxD"  

class SecretKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # apply to specific routes
        if request.url.path.startswith("/get_memories") or request.url.path.startswith("/add_memory") or request.url.path.startswith("/delete_memories") or request.url.path.startswith("/get_memory") or request.url.path.startswith("/update_memory") or request.url.path.startswith("/delete_memory") or request.url.path.startswith("/search_memories") or request.url.path.startswith("/memory_history"):
            secret_key = request.headers.get("X-Secret-Key")
            if secret_key != SECRET_KEY:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Forbidden: Invalid secret key"}
                )
        
        response = await call_next(request)
        return response

# Add middleware
app.add_middleware(SecretKeyMiddleware)

class MemorySearchRequest(BaseModel):
    query: str
    user_id: str


class AddMemoryRequest(BaseModel):
    memory: str
    user_id: str


# Get all memories
@app.post("/get_memories", response_model=Union[List[str], dict])
async def get_memories(
    user_id: str = Form(...), 
    start_date: Optional[str] = Form(None), 
    end_date: Optional[str] = Form(None)
):
    try:
        all_memories = m.get_all(user_id=user_id)
        logger.info(f"Retrieved memories: {all_memories}")

        if not isinstance(all_memories, dict) or 'results' not in all_memories:
            raise HTTPException(status_code=500, detail="Invalid response format from memory store")

        if not all_memories['results']:
            raise HTTPException(status_code=404, detail="User not found")
        
        memories_only = []
        for memory in all_memories['results']:
            if isinstance(memory, dict) and 'memory' in memory:
                memories_only.append(memory['memory'])
            else:
                logger.warning(f"Unexpected memory entry: {memory}")

        if start_date and end_date:
            filtered_memories = [
                memory for memory in all_memories['results']
                if 'created_at' in memory and start_date <= memory['created_at'] <= end_date
            ]
            memories_only = [memory['memory'] for memory in filtered_memories]
        
        return memories_only

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error retrieving memories: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Add memories
@app.post("/add_memory")
async def add_memory(memory: str = Form(...), user_id: str = Form(...)):
    memo = [memory]
    for mem in memo:
        try:
            print(f"Attempting to store memory: {mem}")
            response = m.add(mem, user_id=user_id)
            print(f"Stored memory response: {response}")
            return {"message": "Memory added successfully", "memory_id": response, "user_id": user_id}
        except Exception as e:
            print(f"Error storing memory: {mem}, Error: {e}")
    

# Delete all memories of a specific user
@app.delete("/delete_memories")
async def delete_memory(user_id: str = Form(...)):
    try:
        result = m.delete_all(user_id=user_id)
        return {"message": f"All memories of {user_id} deleted successfully", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Get a memory
@app.get("/get_memory")
async def get_memory(memory_id: str = Form(...)):
    try:
        memory = m.get(memory_id=memory_id)
        return {"message": "Memory found", "result": memory}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

# Get or Update or delete a memory
@app.put("/update_memory")
async def update_memory(
    memory_id: str = Form(...),
    message: str = Form(...)
):
    try:
        updated_memory = m.update(memory_id, message)

        if updated_memory:
            return {"updated_memory": updated_memory}
        else:
            raise HTTPException(status_code=404, detail="Memory not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

# Delete a specific memory using memory_id
@app.delete("/delete_memory")
async def delete_memory(memory_id: str = Form(...)):
    try:
        result = m.delete(memory_id=memory_id)
        return {"message": "Memory deleted successfully", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search_memories")
async def search_memories(
    query: str = Form(...),
    user_id: str = Form(...),
    agent_id: Optional[List[str]] = Form(None),
):
    try:
        filters = {
            "user_id": user_id
        }
        
        # Check if agent_id is provided and not an empty string
        if agent_id and any(agent_id):  # `any(agent_id)` checks if it's not a list of empty strings
            filters["agent_id"] = {"in": agent_id}

        search_results = m.search(query=query, filters=filters)
        print("search result", search_results)
        memories_only = [mem for mem in search_results['results'] if mem['score'] > 0.3]
        return {"query": query, "results": memories_only}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Retrieve the history of a memory
@app.get("/memory_history")
async def get_memory_history(memory_id: str = Form(...)):
    try:
        history = m.history(memory_id)
        
        if history:
            return {"memory_id": memory_id, "history": history}
        else:
            raise HTTPException(status_code=404, detail="No history found for the given memory ID")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8009)

