# Getting Started with Cortex Agents and Slack

## Overview

Cortex Agents simplify AI-powered data interactions via a REST API, combining hybrid search and accurate SQL generation. They streamline workflows by managing context retrieval, natural language to SQL conversion, and LLM orchestration. Response quality is enhanced with in-line citations, answer abstention, and multi-message context handling. Developers benefit from a single API call integration, real-time streamed responses, and reduced latency for optimized applications.

## Github Repository & Step-by-Step Guide for HOL
-- github repository
https://github.com/sfc-gh-anathan/saks-cortex-agents-with-slack 

-- path to quickstart
-- Note that this github repo has been SIGNIFICANTLY MODIFIED. This is only for additional context
[QuickStart Guide](https://quickstarts.snowflake.com/guide/integrate_snowflake_cortex_agents_with_slack/index.html).

-- instructions for getting set up in slack
https://tools.slack.dev/bolt-python/getting-started/ 

## Saks Hands-on-Lab

1. Copy github repo
    -- in your project: rename fill-in-the-env.txt to .env
    -- update your .env file per instructions at top of page


2. Set up Snowflake with preparatory scripts
    -- setup.sql
        validate database and stages
        validate support_tickets.csv
    -- Load files
        semantic files into dash_semantic_models
        pdfs into dash_pdfs
    -- Add Table through "Add Data" for retail_sales_dataset.csv - name file retail_sales_dataset
    -- Validate both tables exist
    -- Validate semantic models via Cortex Analyst in AI & ML
    -- You will need to OVERWRITE the database name with yours (the one with your initials if you needed to do that)
    -- Run cortex_search_service.sql

3. Create Slack App from manifest.json & set .env for BOT and APP tokens
    -- Create your tokens: 
        add a scope of connections:write for the app scope
    -- add your APP and BOT tokens from your Slack Application configuration menus into .env

4. Create key-pairs & update USER
    -- see below

5. Run application






## To create a virtual python3 environment
python3 -m venv .venv
source .venv/bin/activate
which python3
pip install -r requirements.txt


## To generate keys
-- generate a private key
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
--The commands generate a private key in PEM format.
-----BEGIN ENCRYPTED PRIVATE KEY-----
MIIE6T...
-----END ENCRYPTED PRIVATE KEY-----
-- Generate a public key
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
-- The command generates the public key in PEM format.
-----BEGIN PUBLIC KEY-----
MIIBIj...
-----END PUBLIC KEY-----
-- set the key on the Snowflake user

ALTER USER example_user SET RSA_PUBLIC_KEY='MIIBIjANBgkqh...';


## to work with retail data
Use Add Data to upload the .csv file
Add the semantic model to the semantic model stage
change the .env comments to use the retail .yaml file
