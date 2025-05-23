import re
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from dateutil import parser as date_parser


@dataclass
class BuildStep:
    """Represents a single Docker build step."""
    step_id: str
    description: str
    start_time: datetime
    end_time: Optional[datetime]
    duration: Optional[float]
    step_type: str
    layer_info: Optional[str]
    is_cached: bool = False
    parent_steps: List[str] = None
    
    def __post_init__(self):
        if self.parent_steps is None:
            self.parent_steps = []


class DockerLogParser:
    """Parser for Docker build logs supporting both BuildKit and legacy formats."""
    
    # BuildKit patterns
    BUILDKIT_START_PATTERN = re.compile(
        r'#(\d+)\s+\[([^\]]+)\s+(\d+/\d+)\]\s+(.+?)(?:\s+(\d+\.\d+s))?$'
    )
    BUILDKIT_PROGRESS_PATTERN = re.compile(
        r'#(\d+)\s+(\d+\.\d+s)\s+(.+?)$'
    )
    BUILDKIT_DONE_PATTERN = re.compile(
        r'#(\d+)\s+DONE\s+(\d+\.\d+s)$'
    )
    BUILDKIT_CACHED_PATTERN = re.compile(
        r'#(\d+)\s+CACHED(?:\s+\[([^\]]+)\s+(\d+/\d+)\]\s+(.+?))?$'
    )
    # Additional patterns for different BuildKit formats
    BUILDKIT_SIMPLE_PATTERN = re.compile(
        r'#(\d+)\s+\[([^\]]+)\]\s+(.+?)$'
    )
    BUILDKIT_EXTRACTING_PATTERN = re.compile(
        r'#(\d+)\s+extracting\s+(.+?)(?:\s+(\d+\.\d+s))?'
    )
    BUILDKIT_LOADING_PATTERN = re.compile(
        r'#(\d+)\s+loading\s+(.+?)'
    )
    # Pattern for transferring, writing, etc.
    BUILDKIT_TRANSFERRING_PATTERN = re.compile(
        r'#(\d+)\s+(transferring|writing|preparing|sha256:[a-f0-9]+)\s+(.+?)$'
    )
    # Pattern for continuation lines
    BUILDKIT_CONTINUATION_PATTERN = re.compile(
        r'#(\d+)\s+\.\.\.$'
    )
    
    # Legacy Docker patterns
    LEGACY_STEP_PATTERN = re.compile(
        r'Step\s+(\d+/\d+)\s*:\s*(.+?)$'
    )
    LEGACY_USING_CACHE_PATTERN = re.compile(
        r'---> Using cache'
    )
    LEGACY_RUNNING_PATTERN = re.compile(
        r'---> Running in ([a-f0-9]+)'
    )
    
    # Timestamp patterns
    TIMESTAMP_PATTERN = re.compile(
        r'^(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)\s+'
    )
    
    def __init__(self):
        self.steps: Dict[str, BuildStep] = {}
        self.build_start_time: Optional[datetime] = None
        self.is_buildkit = False
        self.relative_time_counter = 0
        
    def parse_logs(self, log_content: str) -> List[BuildStep]:
        """Parse Docker build logs and extract build steps."""
        lines = log_content.strip().split('\n')
        
        # Detect BuildKit vs legacy format
        self._detect_format(lines)
        
        if self.is_buildkit:
            return self._parse_buildkit_logs(lines)
        else:
            return self._parse_legacy_logs(lines)
    
    def _detect_format(self, lines: List[str]) -> None:
        """Detect whether logs are in BuildKit or legacy format."""
        for line in lines[:20]:  # Check first 20 lines
            # Remove timestamp if present
            cleaned_line = self.TIMESTAMP_PATTERN.sub('', line).strip()
            if cleaned_line.startswith('#') and ('DONE' in cleaned_line or 'CACHED' in cleaned_line or '[' in cleaned_line):
                self.is_buildkit = True
                return
        self.is_buildkit = False
    
    def _parse_buildkit_logs(self, lines: List[str]) -> List[BuildStep]:
        """Parse BuildKit format logs."""
        step_start_times = {}
        step_info = {}
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Extract timestamp if present
            timestamp = self._extract_timestamp(line)
            if timestamp and not self.build_start_time:
                self.build_start_time = timestamp
            
            # Remove timestamp from line for pattern matching
            line = self.TIMESTAMP_PATTERN.sub('', line)
            
            # Match BuildKit patterns
            if match := self.BUILDKIT_CACHED_PATTERN.match(line):
                step_id = f"#{match.group(1)}"
                # CACHED can appear with or without additional info
                if match.group(2):  # Has full info
                    step_info[step_id] = BuildStep(
                        step_id=step_id,
                        description=match.group(4) if match.group(4) else "CACHED",
                        start_time=timestamp or self.build_start_time or datetime.now(),
                        end_time=timestamp or self.build_start_time or datetime.now(),
                        duration=0.0,
                        step_type=match.group(2),
                        layer_info=match.group(3),
                        is_cached=True
                    )
                else:  # Just "#N CACHED"
                    if step_id in step_info:
                        step_info[step_id].is_cached = True
                        step_info[step_id].duration = 0.0
                        step_info[step_id].end_time = step_info[step_id].start_time
                
            elif match := self.BUILDKIT_START_PATTERN.match(line):
                step_id = f"#{match.group(1)}"
                if step_id not in step_start_times:
                    step_start_times[step_id] = timestamp or self.build_start_time or datetime.now()
                    step_info[step_id] = BuildStep(
                        step_id=step_id,
                        description=match.group(4),
                        start_time=step_start_times[step_id],
                        end_time=None,
                        duration=None,
                        step_type=match.group(2),
                        layer_info=match.group(3),
                        is_cached=False
                    )
                    
            elif match := self.BUILDKIT_DONE_PATTERN.match(line):
                step_id = f"#{match.group(1)}"
                duration = self._parse_duration(match.group(2))
                if step_id in step_info:
                    step = step_info[step_id]
                    if not step.is_cached:
                        step.duration = duration
                        if step.start_time is not None:
                            step.end_time = step.start_time + timedelta(seconds=duration)
                        else:
                            # If no start time, use relative timing
                            if not self.build_start_time:
                                self.build_start_time = datetime.now()
                            step.start_time = self.build_start_time + timedelta(seconds=self.relative_time_counter)
                            step.end_time = step.start_time + timedelta(seconds=duration)
                            self.relative_time_counter += duration
                        
            elif match := self.BUILDKIT_PROGRESS_PATTERN.match(line):
                step_id = f"#{match.group(1)}"
                if step_id in step_info and not step_info[step_id].end_time:
                    # Update progress
                    pass
                    
            elif match := self.BUILDKIT_SIMPLE_PATTERN.match(line):
                # Handle simple pattern like "#1 [internal] load build definition from Dockerfile"
                step_id = f"#{match.group(1)}"
                if step_id not in step_info:
                    step_info[step_id] = BuildStep(
                        step_id=step_id,
                        description=match.group(3),
                        start_time=timestamp or self.build_start_time or datetime.now(),
                        end_time=None,
                        duration=None,
                        step_type=match.group(2),
                        layer_info="",
                        is_cached=False
                    )
                    
            elif match := self.BUILDKIT_EXTRACTING_PATTERN.match(line):
                # Handle extracting pattern
                step_id = f"#{match.group(1)}"
                if step_id in step_info:
                    # Update existing step with extracting info
                    if match.group(3):  # Has duration
                        duration = self._parse_duration(match.group(3))
                        step_info[step_id].duration = (step_info[step_id].duration or 0) + duration
                        
            elif match := self.BUILDKIT_LOADING_PATTERN.match(line):
                # Handle loading pattern
                step_id = f"#{match.group(1)}"
                # Loading is part of an existing step, don't create new
                
            elif match := self.BUILDKIT_TRANSFERRING_PATTERN.match(line):
                # Handle transferring pattern
                step_id = f"#{match.group(1)}"
                if step_id in step_info:
                    # Update existing step
                    pass
                    
            elif match := self.BUILDKIT_CONTINUATION_PATTERN.match(line):
                # Handle continuation pattern
                step_id = f"#{match.group(1)}"
                # This is just a continuation marker, ignore
                
            elif line.strip().startswith('#') and ' ' in line:
                # Fallback pattern for any #N lines we haven't caught
                parts = line.strip().split(' ', 2)
                if len(parts) >= 2 and parts[0].startswith('#'):
                    try:
                        step_num = int(parts[0][1:])
                        step_id = f"#{step_num}"
                        description = ' '.join(parts[1:]) if len(parts) > 1 else "Unknown"
                        
                        if step_id not in step_info:
                            step_info[step_id] = BuildStep(
                                step_id=step_id,
                                description=description,
                                start_time=timestamp or self.build_start_time or datetime.now(),
                                end_time=None,
                                duration=None,
                                step_type="OTHER",
                                layer_info="",
                                is_cached=False
                            )
                    except ValueError:
                        # Not a valid step number, ignore
                        pass
        
        # Calculate relative times if no absolute timestamps
        if not self.build_start_time:
            self._calculate_relative_times(list(step_info.values()))
            
        return list(step_info.values())
    
    def _parse_legacy_logs(self, lines: List[str]) -> List[BuildStep]:
        """Parse legacy Docker build format logs."""
        steps = []
        current_step = None
        step_counter = 0
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
                
            # Extract timestamp
            timestamp = self._extract_timestamp(line)
            if timestamp and not self.build_start_time:
                self.build_start_time = timestamp
                
            # Remove timestamp from line
            line = self.TIMESTAMP_PATTERN.sub('', line)
            
            # Match legacy patterns
            if match := self.LEGACY_STEP_PATTERN.match(line):
                # Save previous step
                if current_step:
                    steps.append(current_step)
                    
                step_counter += 1
                current_step = BuildStep(
                    step_id=f"Step {step_counter}",
                    description=match.group(2),
                    start_time=timestamp or self.build_start_time or datetime.now(),
                    end_time=None,
                    duration=None,
                    step_type="RUN" if "RUN" in match.group(2) else "OTHER",
                    layer_info=match.group(1),
                    is_cached=False
                )
                
            elif current_step and self.LEGACY_USING_CACHE_PATTERN.match(line):
                current_step.is_cached = True
                current_step.duration = 0.0
                current_step.end_time = current_step.start_time
                
            elif current_step and i < len(lines) - 1:
                # Check if next line starts a new step
                next_line = lines[i + 1].strip()
                next_line = self.TIMESTAMP_PATTERN.sub('', next_line)
                if self.LEGACY_STEP_PATTERN.match(next_line):
                    next_timestamp = self._extract_timestamp(lines[i + 1])
                    if current_step.start_time and next_timestamp:
                        current_step.end_time = next_timestamp
                        current_step.duration = (next_timestamp - current_step.start_time).total_seconds()
        
        # Add last step
        if current_step:
            steps.append(current_step)
            
        return steps
    
    def _extract_timestamp(self, line: str) -> Optional[datetime]:
        """Extract timestamp from log line."""
        match = self.TIMESTAMP_PATTERN.match(line)
        if match:
            try:
                return date_parser.parse(match.group(1))
            except:
                pass
        return None
    
    def _parse_duration(self, duration_str: str) -> float:
        """Parse duration string (e.g., '2.1s') to float seconds."""
        return float(duration_str.rstrip('s'))
    
    def _calculate_relative_times(self, steps: List[BuildStep]) -> None:
        """Calculate relative times when no absolute timestamps are available."""
        if not steps:
            return
            
        # Use current time as base
        base_time = datetime.now()
        self.build_start_time = base_time
        
        # Sort steps by ID to get order
        steps.sort(key=lambda s: int(s.step_id.lstrip('#Step ')))
        
        current_time = base_time
        for step in steps:
            if step.is_cached:
                step.start_time = current_time
                step.end_time = current_time
            else:
                step.start_time = current_time
                if step.duration is not None:
                    step.end_time = current_time + timedelta(seconds=step.duration)
                    current_time = step.end_time
                else:
                    # Estimate 1 second for steps without duration
                    step.duration = 1.0
                    step.end_time = current_time + timedelta(seconds=1)
                    current_time = step.end_time
    
    def detect_parallelism(self, steps: List[BuildStep]) -> Dict[str, List[str]]:
        """Detect which steps run in parallel."""
        parallel_groups = {}
        
        # Sort steps by start time, filtering out any with None start_time
        valid_steps = [s for s in steps if s.start_time is not None]
        sorted_steps = sorted(valid_steps, key=lambda s: s.start_time)
        
        for i, step in enumerate(sorted_steps):
            parallel_with = []
            for j, other in enumerate(sorted_steps):
                if i != j and self._steps_overlap(step, other):
                    parallel_with.append(other.step_id)
            
            if parallel_with:
                parallel_groups[step.step_id] = parallel_with
                
        return parallel_groups
    
    def _steps_overlap(self, step1: BuildStep, step2: BuildStep) -> bool:
        """Check if two steps overlap in time."""
        if not all([step1.start_time, step1.end_time, step2.start_time, step2.end_time]):
            return False
            
        return not (step1.end_time <= step2.start_time or step2.end_time <= step1.start_time)
    
    def identify_bottlenecks(self, steps: List[BuildStep], threshold_percentile: float = 75) -> List[BuildStep]:
        """Identify bottleneck steps based on duration."""
        non_cached_steps = [s for s in steps if not s.is_cached and s.duration is not None]
        if not non_cached_steps:
            return []
            
        durations = [s.duration for s in non_cached_steps]
        threshold = sorted(durations)[int(len(durations) * threshold_percentile / 100)]
        
        return [s for s in non_cached_steps if s.duration >= threshold]