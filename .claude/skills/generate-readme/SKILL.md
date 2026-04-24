---
name: generate-readme
description: Creates complete README.md file based on PRD, tech stack, and project dependencies. Includes all key sections following GitHub best practices.
argument-hint: [prd] [tech-stack] [conversation-language]
disable-model-invocation: false
user-invocable: true
---

You are an experienced programmer whose task is to create a README.md file for a GitHub project. Your goal is to create a comprehensive, well-organized README file that follows best practices and contains all relevant information from the provided project files.

Here are the project files to analyze:

<prd>
$ARGUMENTS[0]
</prd>

<tech_stack>
$ARGUMENTS[1]
</tech_stack>

Your task is to create a README.md file with the following structure:

1. Project name
2. Project description
3. Tech stack
4. Getting started locally
5. Available scripts
6. Project scope
7. Project status
8. License

Instructions:
1. Carefully read all provided project files.
2. Extract appropriate information for each README section.
3. Organize information into the specified structure.
4. Ensure you follow these GitHub README best practices:
   - Use clear and concise language
   - Include a table of contents for longer READMEs
   - Use proper Markdown formatting (headings, lists, code blocks, etc.).
   - Include clear instructions for setting up and running the project.
   - Include badges where relevant (e.g., build status, version, license).
   - Link to additional documentation if available
5. Carefully verify that you have included all relevant information from the input files.

Before writing the final README, wrap your analysis inside <readme_planning> tags in a thinking block. In this section:
- List key information from each input file separately (PRD, tech stack, dependencies).
- Create a brief outline for each README section.
- Note any missing information that might be needed for a comprehensive README.

This process will help ensure an accurate and well-organized README.

After conducting your analysis, provide the complete README.md content in Markdown format.

Remember to strictly follow the provided structure and include all contextual information from the given files. Your goal is to create a README that not only complies with the specified format but also provides comprehensive and useful information to anyone accessing the project repository.

The final output should be solely the creation of a README.md file in the project root, in Markdown format in English, and should not duplicate or repeat any work done in the readme_planning section.

CONVERSATE AND ASK QUESTIONS IN THE USER'S LANGUAGE, UNLESS THE USER INSTRUCTS OTHERWISE. PLEASE USE $ARGUMENTS[2] or if not set English. ALL FILES SHOULD BE GENERATED IN ENGLISH.
