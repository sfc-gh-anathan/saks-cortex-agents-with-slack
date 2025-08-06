USE SLACK_DEMO.SLACK_SCHEMA;
USE WAREHOUSE SLACK_S;

create warehouse TEMP_MEDIUM warehouse_size = 'MEDIUM' auto_suspend = 60 auto_resume = true;
use warehouse TEMP_MEDIUM;

-- Pull the data from a stage into a table. 
-- Note the use of cortex.parse_document function to parse the PDF files.
create or replace table parse_pdfs as 
select relative_path, SNOWFLAKE.CORTEX.PARSE_DOCUMENT(@SLACK_DEMO.SLACK_SCHEMA.SLACK_PDFS,relative_path,{'mode':'LAYOUT'}) as data
    from directory(@SLACK_DEMO.SLACK_SCHEMA.SLACK_PDFS);

-- Create a table with parsed content from the PDFs
-- Note the use of SNOWFLAKE.CORTEX.SPLIT_TEXT_RECURSIVE_CHARACTER function to split the content into chunks.
create or replace table parsed_pdfs as (
    with tmp_parsed as (select
        relative_path,
        SNOWFLAKE.CORTEX.SPLIT_TEXT_RECURSIVE_CHARACTER(TO_VARIANT(data):content, 'MARKDOWN', 750, 200) AS chunks
    from parse_pdfs where TO_VARIANT(data):content is not null)
    select
        TO_VARCHAR(c.value) as PAGE_CONTENT,
        REGEXP_REPLACE(relative_path, '\\.pdf$', '') as TITLE,
        'SLACK_DEMO.SLACK_SCHEMA.SLACK_PDFS' as INPUT_STAGE,
        RELATIVE_PATH as RELATIVE_PATH
    from tmp_parsed p, lateral FLATTEN(INPUT => p.chunks) c
);

-- Create a search service on the parsed PDF content.
-- This service will allow you to search through the parsed content.
-- This search service is set to target a lag of 1 hour, meaning it will update the search index every hour.
-- It will be called by the Cortex Agent via the Cortex Search Service API (routed from the Cortex Agent to the Snowflake Cortex Search Service).
create or replace CORTEX SEARCH SERVICE SLACK_DEMO.SLACK_SCHEMA.info_search
ON PAGE_CONTENT
WAREHOUSE = SLACK_S
TARGET_LAG = '1 hour'
AS (
    SELECT '' AS PAGE_URL, PAGE_CONTENT, TITLE, RELATIVE_PATH
    FROM parsed_pdfs
);

drop warehouse TEMP_MEDIUM;

-- Create the REFINE_QUERY stored procedure
-- This procedure is called by the Slack bot to refine user prompts using Snowflake Cortex
-- It reads the semantic model from the stage and uses Cortex to provide intelligent suggestions
CREATE OR REPLACE PROCEDURE REFINE_QUERY("STAGE_PATH" VARCHAR, "FILE_NAME" VARCHAR, "USER_PROMPT" VARCHAR)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.9'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'refine_query'
EXECUTE AS OWNER
AS '
def refine_query(session, stage_path, file_name, user_prompt):
    try:
        # Construct the full file path
        if not stage_path.endswith("/"):
            full_path = stage_path + "/" + file_name
        else:
            full_path = stage_path + file_name
        
        # Use the Snowpark DataFrame API to read the file
        df = session.read.option("FIELD_DELIMITER", "NONE").option("RECORD_DELIMITER", "NONE").option("SKIP_HEADER", 0).csv(full_path)
        
        # Collect all rows and concatenate them
        rows = df.collect()
        file_content = ""
        
        for row in rows:
            if row[0] is not None:
                file_content += str(row[0])
        
        # Create the prompt for Cortex to analyze the users query against the semantic model
        cortex_prompt = f"""
User Query: "{user_prompt}"

Semantic Model: {file_content}

Check if this query can be executed against the semantic model. Look at the dimensions, facts, time_dimensions, and their descriptions to see if the requested data exists and if key details are specified.

Always respond in exactly this format:
- If data not available: "This data is not available in the current dataset."
- If missing clear requirement details: from 1 to 3 [suggestion]"
- If complete: "Prompt is appropriately specific."
- Do NOT restate the prompt itself and do NOT indicate what you will do to help refine their query. Only provide recommendations.

Be direct and concise.

"""
        
        # Call Cortex with the analysis prompt
        cortex_query = """
        SELECT SNOWFLAKE.CORTEX.COMPLETE(''claude-3-5-sonnet'', ?) as result
        """
        
        cortex_result = session.sql(cortex_query, [cortex_prompt]).collect()
        
        if cortex_result and len(cortex_result) > 0:
            return cortex_result[0][0] if cortex_result[0][0] is not None else "No result from Cortex"
        else:
            return "No response from Cortex"
        
    except Exception as e:
        return f"Error in refine_query: {str(e)}"
';

-- Grant necessary permissions (adjust roles as needed)
GRANT USAGE ON PROCEDURE REFINE_QUERY(VARCHAR, VARCHAR, VARCHAR) TO ROLE ACCOUNTADMIN;