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