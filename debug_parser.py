#!/usr/bin/env python3
"""Debug script to understand why buildkit_complex.log isn't being parsed correctly."""

import sys
import re
from log_parser import DockerLogParser

def debug_parse():
    # Read the log file
    with open('example_logs/buildkit_complex.log', 'r') as f:
        content = f.read()
    
    print("=== Log File Info ===")
    lines = content.strip().split('\n')
    print(f"Total lines: {len(lines)}")
    print(f"First 5 lines:")
    for i, line in enumerate(lines[:5]):
        print(f"  {i}: {line}")
    
    # Initialize parser
    parser = DockerLogParser()
    
    # Detect format
    parser._detect_format(lines)
    print(f"\nDetected format: {'BuildKit' if parser.is_buildkit else 'Legacy'}")
    
    # Test timestamp extraction
    print("\n=== Timestamp Extraction Test ===")
    for i, line in enumerate(lines[:3]):
        timestamp = parser._extract_timestamp(line)
        print(f"Line {i}: {timestamp}")
        cleaned = parser.TIMESTAMP_PATTERN.sub('', line)
        print(f"  Cleaned: {cleaned}")
    
    # Test pattern matching
    print("\n=== Pattern Matching Test ===")
    test_patterns = [
        ("BUILDKIT_START", parser.BUILDKIT_START_PATTERN),
        ("BUILDKIT_DONE", parser.BUILDKIT_DONE_PATTERN),
        ("BUILDKIT_CACHED", parser.BUILDKIT_CACHED_PATTERN),
        ("BUILDKIT_SIMPLE", parser.BUILDKIT_SIMPLE_PATTERN),
    ]
    
    for line_num in [0, 1, 2, 4, 13, 32]:  # Test specific lines
        if line_num < len(lines):
            line = lines[line_num]
            cleaned = parser.TIMESTAMP_PATTERN.sub('', line).strip()
            print(f"\nLine {line_num}: {cleaned[:80]}...")
            
            for pattern_name, pattern in test_patterns:
                match = pattern.match(cleaned)
                if match:
                    print(f"  ✓ {pattern_name} matched: {match.groups()}")
                else:
                    print(f"  ✗ {pattern_name} no match")
    
    # Try full parsing
    print("\n=== Full Parse Attempt ===")
    steps = parser.parse_logs(content)
    print(f"Parsed {len(steps)} steps")
    
    if steps:
        print("\nFirst 5 steps:")
        for step in steps[:5]:
            print(f"  {step.step_id}: {step.description[:50]}... (cached={step.is_cached})")
    else:
        print("No steps parsed!")
        
        # Debug the parsing process
        print("\n=== Debug Parse Process ===")
        parser_debug = DockerLogParser()
        parser_debug.is_buildkit = True
        step_info = {}
        
        for i, line in enumerate(lines[:20]):
            line = line.strip()
            if not line:
                continue
            
            # Remove timestamp
            cleaned = parser_debug.TIMESTAMP_PATTERN.sub('', line).strip()
            print(f"\nLine {i}: {cleaned[:60]}...")
            
            # Try all patterns
            patterns = [
                ("CACHED", parser_debug.BUILDKIT_CACHED_PATTERN),
                ("START", parser_debug.BUILDKIT_START_PATTERN),
                ("DONE", parser_debug.BUILDKIT_DONE_PATTERN),
                ("SIMPLE", parser_debug.BUILDKIT_SIMPLE_PATTERN),
                ("PROGRESS", parser_debug.BUILDKIT_PROGRESS_PATTERN),
            ]
            
            matched = False
            for pattern_name, pattern in patterns:
                match = pattern.match(cleaned)
                if match:
                    print(f"  Matched {pattern_name}: {match.groups()}")
                    matched = True
                    break
            
            if not matched and cleaned.startswith('#'):
                # Try the fallback pattern
                parts = cleaned.split(' ', 2)
                if len(parts) >= 2 and parts[0].startswith('#'):
                    try:
                        step_num = int(parts[0][1:])
                        print(f"  Fallback: step #{step_num}, desc: {' '.join(parts[1:])[:40]}...")
                    except ValueError:
                        print(f"  Failed to parse step number from: {parts[0]}")

if __name__ == "__main__":
    debug_parse()