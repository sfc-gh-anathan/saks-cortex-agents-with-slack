
CREATE DATABASE IF NOT EXISTS SLACK_DEMO;
CREATE SCHEMA IF NOT EXISTS SLACK_SCHEMA;
CREATE WAREHOUSE IF NOT EXISTS SLACK_S WAREHOUSE_SIZE=SMALL;
USE SLACK_DEMO.SLACK_SCHEMA;
USE WAREHOUSE SLACK_S;

-- Run the following statement to create a Snowflake managed internal stage to store the semantic model specification file.
create or replace stage SLACK_SEMANTIC_MODELS encryption = (TYPE = 'SNOWFLAKE_SSE') directory = ( ENABLE = true );

-- Run the following statement to create a Snowflake managed internal stage to store the PDF documents.
 create or replace stage SLACK_PDFS encryption = (TYPE = 'SNOWFLAKE_SSE') directory = ( ENABLE = true );
