#!/usr/bin/env python3
"""
Script to fix import issues in router files
"""
import os
import re

def fix_imports_in_file(file_path):
    """Fix imports in a single file"""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace get_current_user with get_current_teacher
    content = content.replace('get_current_user', 'get_current_teacher')
    
    # Replace require_student_or_teacher with require_teacher
    content = content.replace('require_student_or_teacher', 'require_teacher')
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"Fixed imports in {file_path}")

def main():
    """Fix all router files"""
    router_dir = "routers"
    
    for filename in os.listdir(router_dir):
        if filename.endswith('.py'):
            file_path = os.path.join(router_dir, filename)
            fix_imports_in_file(file_path)

if __name__ == "__main__":
    main()
