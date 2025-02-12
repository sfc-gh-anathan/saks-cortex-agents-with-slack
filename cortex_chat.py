import requests
import json
import time

DEBUG = True

class CortexChat:
    def __init__(self, 
            agent_url: str, 
            vehicles_info_search_service: str, 
            semantic_model: str,
            model: str, 
            jwt: str
        ):
        self.agent_url = agent_url
        self.model = model
        self.vehicles_info_search_service = vehicles_info_search_service
        self.semantic_model = semantic_model
        self.jwt = jwt

    def execute_sql(self, sql: str) -> str:    
        sql_url = self.sql_statement_url
        headers = {
            "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.jwt}"  
        }
        
        data = {
            "statement": sql,
            "timeout": 60  # timeout in seconds
        }
        response = requests.post(sql_url, headers=headers, json=data)
        response.raise_for_status()
        response_data = response.json()

        query_id = response_data.get('statementHandle')

        if DEBUG:
            print(f"execute_sql response: {response_data}")
            print(f"query_id: {query_id}")

        if not query_id:
            raise ValueError("No query ID found in response")
            
        return query_id

    def retrieve_response(self, query: str) -> dict[str, any]:
        url = self.agent_url
        headers = {
            'X-Snowflake-Authorization-Token-Type': 'KEYPAIR_JWT',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f"Bearer {self.jwt}"
        }
        data = {
            "model": self.model,
            "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": query
                    }
                ]
            }
            ],
            "tools": [
                {
                    "tool_spec": {
                        "type": "cortex_search",
                        "name": "vehicles_info_search"
                    }
                },
                {
                    "tool_spec": {
                        "type": "cortex_analyst_text_to_sql",
                        "name": "supply_chain"
                    }
                }
            ],
            "tool_resources": {
                "vehicles_info_search": {
                    "name": self.vehicles_info_search_service,
                    "max_results": 1,
                    "title_column": "title",
                    "id_column": "relative_path",
                },
                "supply_chain": {
                    "semantic_model_file": self.semantic_model
                }
            },
        }
        response = requests.post(url, headers=headers, json=data)
        if DEBUG:
            print(response.text)
        if response.status_code == 200:
            return self.parse_response(response)
        else:
            print(f"Error: Received status code {response.status_code}")
            return {"text":response.text}

    def parse_delta_content(self,content: list) -> dict[str, any]:
        """Parse different types of content from the delta."""
        result = {
            'text': '',
            'tool_use': [],
            'tool_results': []
        }
        
        for entry in content:
            entry_type = entry.get('type')
            if entry_type == 'text':
                result['text'] += entry.get('text', '')
            elif entry_type == 'tool_use':
                result['tool_use'].append(entry.get('tool_use', {}))
            elif entry_type == 'tool_results':
                result['tool_results'].append(entry.get('tool_results', {}))
        
        return result

    def process_sse_line(self,line: str) -> dict[str, any]:
        """Process a single SSE line and return parsed content."""
        if not line.startswith('data: '):
            return {}
        
        try:
            json_str = line[6:].strip()  # Remove 'data: ' prefix
            if json_str == '[DONE]':
                return {'type': 'done'}
                
            data = json.loads(json_str)
            if data.get('object') == 'messages.delta':
                delta = data.get('delta', {})
                if 'content' in delta:
                    return {
                        'type': 'message',
                        'content': self.parse_delta_content(delta['content'])
                    }
            return {'type': 'other', 'data': data}
        except json.JSONDecodeError:
            return {'type': 'error', 'message': f'Failed to parse: {line}'}
    
    def parse_response(self,response: requests.Response) -> dict[str, any]:
        """Parse and print the SSE chat response with improved organization."""
        accumulated = {
            'text': '',
            'tool_use': [],
            'tool_results': [],
            'other': []
        }

        for line in response.iter_lines():
            if line:
                result = self.process_sse_line(line.decode('utf-8'))
                
                if result.get('type') == 'message':
                    content = result['content']
                    accumulated['text'] += content['text']
                    accumulated['tool_use'].extend(content['tool_use'])
                    accumulated['tool_results'].extend(content['tool_results'])
                elif result.get('type') == 'other':
                    accumulated['other'].append(result['data'])

        text = ''
        sql = ''
        citations = ''

        if accumulated['text']:
            text = accumulated['text']

        if DEBUG:
            print("\n=== Complete Response ===")

            print("\n--- Generated Text ---")
            print(text)

            if accumulated['tool_use']:
                print("\n--- Tool Usage ---")
                print(json.dumps(accumulated['tool_use'], indent=2))

            if accumulated['other']:
                print("\n--- Other Messages ---")
                print(json.dumps(accumulated['other'], indent=2))

            if accumulated['tool_results']:
                print("\n--- Tool Results ---")
                print(json.dumps(accumulated['tool_results'], indent=2))

        if accumulated['tool_results']:
            for result in accumulated['tool_results']:
                for k,v in result.items():
                    if k == 'content':
                        if DEBUG:
                            print(v)
                        for content in v:
                            if DEBUG:
                                print(content)
                            if 'sql' in content['json']:
                                sql = content['json']['sql']
                            elif 'searchResults' in content['json']:
                                search_results = content['json']['searchResults']
                                for search_result in search_results:
                                    citations += f"{search_result['text']}"
                                text = text.replace("【†1†】","").replace("【†2†】","").replace("【†3†】","").replace(" .",".") + "*"
                                citations = f"{search_result['doc_title']} \n {citations} \n\n[Source: {search_result['doc_id']}]"

        return {"text": text, "sql": sql, "citations": citations}
       
    def chat(self, query: str) -> any:
        response = self.retrieve_response(query)
        return response
