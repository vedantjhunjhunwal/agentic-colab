"""
============================================================
  DSL Compiler – Listing File Generator
  Produces a numbered source listing interleaved with errors
  (Required by assignment: each error references a line number)
============================================================
"""

from typing import List, Dict
from dataclasses import dataclass


@dataclass
class CompilerMessage:
    phase:   str    # "LEX", "PARSE", "SEM", "ICG"
    level:   str    # "ERROR", "WARNING", "INFO"
    line:    int
    col:     int
    message: str

    def __str__(self):
        col_info = f", Col {self.col}" if self.col else ""
        return f"  *** [{self.phase} {self.level}] Line {self.line}{col_info}: {self.message}"


class ListingGenerator:
    def __init__(self, source: str):
        self.source_lines: List[str] = source.splitlines()
        self.messages: List[CompilerMessage] = []

    def add_message(self, phase: str, level: str, line: int, col: int, msg: str):
        self.messages.append(CompilerMessage(phase, level, line, col, msg))

    def add_all_lex_errors(self, errors):
        for err in errors:
            self.add_message("LEX", "ERROR", err.line, err.col, err.message)

    def add_all_parse_errors(self, errors):
        for err in errors:
            self.add_message("PARSE", "ERROR", err.line, err.col, err.message)

    def add_all_sem_errors(self, errors: List[str]):
        for err in errors:
            # Parse out line number from "[SEM ERROR] Line N: ..."
            import re
            m = re.match(r'\[SEM ERROR\]\s+Line\s+(\d+):\s+(.*)', err)
            if m:
                line = int(m.group(1))
                msg  = m.group(2)
            else:
                line = 0
                msg  = err
            self.add_message("SEM", "ERROR", line, 0, msg)

    def generate(self, output_path: str = None) -> str:
        """Build the listing string, optionally write to file."""
        # Group messages by line number
        msg_map: Dict[int, List[CompilerMessage]] = {}
        for m in self.messages:
            msg_map.setdefault(m.line, []).append(m)

        lines_out = []
        lines_out.append("=" * 75)
        lines_out.append("  COMPILER LISTING FILE")
        lines_out.append("  Source lines numbered, errors interleaved below relevant line")
        lines_out.append("=" * 75)
        lines_out.append("")

        # Emit line 0 messages (global / no-line errors)
        for msg in msg_map.get(0, []):
            lines_out.append(str(msg))

        # Emit each source line + any messages for that line
        for i, src_line in enumerate(self.source_lines, start=1):
            lines_out.append(f"  {i:4d} | {src_line}")
            for msg in msg_map.get(i, []):
                lines_out.append(str(msg))
                if msg.col:
                    arrow = ' ' * (msg.col + 8) + '^'
                    lines_out.append(f"  {arrow}")

        lines_out.append("")
        lines_out.append("=" * 75)

        # Summary
        total_errors = sum(1 for m in self.messages if m.level == "ERROR")
        total_warns  = sum(1 for m in self.messages if m.level == "WARNING")
        lines_out.append(f"  COMPILATION SUMMARY")
        lines_out.append(f"  Total lines: {len(self.source_lines)}")
        lines_out.append(f"  Errors:      {total_errors}")
        lines_out.append(f"  Warnings:    {total_warns}")
        if total_errors == 0:
            lines_out.append(f"  Status:      ✓ COMPILATION SUCCESSFUL")
        else:
            lines_out.append(f"  Status:      ✗ COMPILATION FAILED ({total_errors} error(s))")
        lines_out.append("=" * 75)

        result = '\n'.join(lines_out)

        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result)

        return result

    @property
    def error_count(self) -> int:
        return sum(1 for m in self.messages if m.level == "ERROR")
