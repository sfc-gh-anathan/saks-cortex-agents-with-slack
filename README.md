# Getting Started with Cortex Agents and Slack

## Overview

Cortex Agents simplify AI-powered data interactions via a REST API, combining hybrid search and accurate SQL generation. They streamline workflows by managing context retrieval, natural language to SQL conversion, and LLM orchestration. Response quality is enhanced with in-line citations, answer abstention, and multi-message context handling. Developers benefit from a single API call integration, real-time streamed responses, and reduced latency for optimized applications.

## Step-by-Step Guide

For prerequisites, environment setup, step-by-step guide and instructions, please refer to the [QuickStart Guide](https://quickstarts.snowflake.com/guide/integrate_snowflake_cortex_agents_with_slack/index.html).

## Saks Hands-on-Lab
-- github repository
https://github.com/sfc-gh-anathan/saks-cortex-agents-with-slack 

-- instructions for getting set up in slack
https://tools.slack.dev/bolt-python/getting-started/ 

-- in your project: rename fill-in-the-env.txt to .env
-- update your .env file per instructions at top of page
-- you can retrieve your APP and BOT tokens from your Slack Application configuration menus


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
