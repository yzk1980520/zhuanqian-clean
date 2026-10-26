#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fix all cron jobs to use local delivery instead of feishu
"""

import subprocess
import sys
import re

def get_cron_jobs():
    """Get all cron jobs and their IDs"""
    result = subprocess.run(
        ['hermes', 'cron', 'list'],
        capture_output=True,
        text=True
    )
    
    jobs = []
    current_id = None
    current_name = None
    current_deliver = None
    
    for line in result.stdout.split('\n'):
        # Match job ID
        id_match = re.search(r'^\s+([a-f0-9]{12})\s+\[active\]', line)
        if id_match:
            current_id = id_match.group(1)
        
        # Match job name
        name_match = re.search(r'Name:\s+(.+)', line)
        if name_match:
            current_name = name_match.group(1).strip()
        
        # Match deliver target
        deliver_match = re.search(r'Deliver:\s+(.+)', line)
        if deliver_match:
            current_deliver = deliver_match.group(1).strip()
            if current_id and current_deliver.startswith('feishu'):
                jobs.append({
                    'id': current_id,
                    'name': current_name,
                    'deliver': current_deliver
                })
    
    return jobs

def fix_job(job_id):
    """Change a job's delivery to local"""
    result = subprocess.run(
        ['hermes', 'cron', 'edit', job_id, '--deliver', 'local'],
        capture_output=True,
        text=True
    )
    return result.returncode == 0, result.stdout, result.stderr

def main():
    
    jobs = get_cron_jobs()
    print(f"Found {len(jobs)} jobs using Feishu delivery:\n")
    
    for job in jobs:
        print(f"  - {job['name']} ({job['id']})")
    
    
    fixed = 0
    failed = 0
    
    for job in jobs:
        success, stdout, stderr = fix_job(job['id'])
        if success:
            print(f"  ✓ Fixed: {job['name']}")
            fixed += 1
        else:
            print(f"  ✗ Failed: {job['name']} - {stderr}")
            failed += 1
    
    print(f"\n=== Summary ===")
    print(f"Fixed: {fixed}")
    print(f"Failed: {failed}")
    
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
