-- ******************************************************************
-- update your database name everywhere to DASH_DB_<your initials>
-- update warehouse to DASH_S_<your initials>
-- ******************************************************************

USE DASH_DB.DASH_SCHEMA;
USE WAREHOUSE DASH_S;

create warehouse TEMP_LARGE warehouse_size = 'large';
use warehouse TEMP_LARGE;

-- Pull the data from a stage into a table. 
-- Note the use of cortex.parse_document function to parse the PDF files.
create or replace table parse_pdfs as 
select relative_path, SNOWFLAKE.CORTEX.PARSE_DOCUMENT(@DASH_DB.DASH_SCHEMA.DASH_PDFS,relative_path,{'mode':'LAYOUT'}) as data
    from directory(@DASH_DB.DASH_SCHEMA.DASH_PDFS);

-- Create a table with parsed content from the PDFs
-- Note the use of SNOWFLAKE.CORTEX.SPLIT_TEXT_RECURSIVE_CHARACTER function to split the content into chunks.
create or replace table parsed_pdfs as (
    with tmp_parsed as (select
        relative_path,
        SNOWFLAKE.CORTEX.SPLIT_TEXT_RECURSIVE_CHARACTER(TO_VARIANT(data):content, 'MARKDOWN', 500, 150) AS chunks
    from parse_pdfs where TO_VARIANT(data):content is not null)
    select
        TO_VARCHAR(c.value) as PAGE_CONTENT,
        REGEXP_REPLACE(relative_path, '\\.pdf$', '') as TITLE,
        'DASH_DB.DASH_SCHEMA.DASH_PDFS' as INPUT_STAGE,
        RELATIVE_PATH as RELATIVE_PATH
    from tmp_parsed p, lateral FLATTEN(INPUT => p.chunks) c
);

-- Create a search service on the parsed PDF content.
-- This service will allow you to search through the parsed content.
-- This search service is set to target a lag of 1 hour, meaning it will update the search index every hour.
-- It will be called by the Cortex Agent via the Cortex Search Service API (routed from the Cortex Agent to the Snowflake Cortex Search Service).
create or replace CORTEX SEARCH SERVICE DASH_DB.DASH_SCHEMA.info_search
ON PAGE_CONTENT
WAREHOUSE = DASH_S
TARGET_LAG = '1 hour'
AS (
    SELECT '' AS PAGE_URL, PAGE_CONTENT, TITLE, RELATIVE_PATH
    FROM parsed_pdfs
);

drop warehouse TEMP_LARGE;