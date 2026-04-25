import json
import argparse
from re import I

def load_json_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return {"content": file.read(), "file_path": file_path}

def load_json_content(content):
    return {"content": content, "file_path": None}

def write_markdown_file(content, file_path):
    if not file_path.endswith('.md'):
        file_path = file_path + '.md'
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(content)

def format_value(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ", ".join(format_value(i) for i in v)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {format_value(val)}" for k, val in v.items())
    if isinstance(v, str):
        return (v.replace('\b', '\\b').replace('\f', '\\f')
                 .replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t'))
    return str(v)

def dict_to_bold_pairs(d):
    return "  \n".join(f"**{k.capitalize()}:** {format_value(v)}" for k, v in d.items())

def dict_to_table(d):
    lines = ["| Key | Value |", "| --- | --- |"]
    for k, v in d.items():
        lines.append(f"| {k} | {format_value(v)} |")
    return "\n".join(lines)

def list_of_dicts_to_table(items):
    keys = list(dict.fromkeys(k for item in items for k in item.keys()))
    lines = [
        "| " + " | ".join(keys) + " |",
        "| " + " | ".join("---" for _ in keys) + " |",
    ]
    for item in items:
        lines.append("| " + " | ".join(format_value(item.get(k)) for k in keys) + " |")
    return "\n".join(lines)

def is_simple(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return True
    if isinstance(v, list):
        return all(not isinstance(i, (dict, list)) for i in v)
    return False

MAX_HEADING_LEVEL = 6

def build_section_markdown(key, value, level=2):
    level = min(level, MAX_HEADING_LEVEL)
    header = f"{'#' * level} {key.capitalize()}"
    if isinstance(value, dict):
        if not value:
            body = "*(empty)*"
        elif all(is_simple(v) for v in value.values()) or level == MAX_HEADING_LEVEL:
            body = dict_to_bold_pairs(value)
        else:
            simple = {k: v for k, v in value.items() if is_simple(v)}
            complex_ = {k: v for k, v in value.items() if not is_simple(v)}
            parts = []
            if simple:
                parts.append(dict_to_bold_pairs(simple))
            for k, v in complex_.items():
                parts.append(build_section_markdown(k, v, level + 1))
            return f"{header}\n\n" + "\n\n".join(parts)
    elif isinstance(value, list):
        if not value:
            body = "*(empty)*"
        elif all(isinstance(i, dict) for i in value):
            body = list_of_dicts_to_table(value)
        else:
            blocks = []
            bullet_buffer = []
            for item in value:
                if isinstance(item, dict):
                    if bullet_buffer:
                        blocks.append("\n".join(bullet_buffer))
                        bullet_buffer = []
                    blocks.append(dict_to_table(item))
                else:
                    bullet_buffer.append(f"* {format_value(item)}")
            if bullet_buffer:
                blocks.append("\n".join(bullet_buffer))
            body = "\n\n".join(blocks)
    else:
        body = format_value(value)
    return f"{header}\n\n{body}"

def convert_json_to_markdown(json_data):
    file_name = json_data.get('file_path').split('/')[-1].split('.')[0]
    content = json.loads(json_data.get('content'))

    sections = []
    if file_name:
        sections.append(f"# {file_name.capitalize()}")

    for key, value in content.items():
        sections.append(build_section_markdown(key, value))

    return "\n\n".join(sections) + "\n"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-file', type=str, help='The JSON file to convert to markdown')
    parser.add_argument('--from-content', type=str, help='The JSON content to convert to markdown')
    parser.add_argument('--to-file', type=str, help='The markdown file to write to')

    args = parser.parse_args()
    
    if args.from_file:
        json_data = load_json_file(args.from_file)
    elif args.from_content:
        json_data = load_json_content(args.from_content)
    else:
        raise ValueError('No input source provided')
    
    markdown_data = convert_json_to_markdown(json_data)

    if args.to_file:
        write_markdown_file(markdown_data, args.to_file)
    else:
        print(markdown_data)

if __name__ == '__main__':
    main()