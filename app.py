import streamlit as st
import tempfile
import os
from datetime import datetime
from log_parser import DockerLogParser
from visualizer import BuildWaterfallVisualizer


def main():
    st.set_page_config(
        page_title="Docker Build Waterfall Viewer",
        page_icon="🐳",
        layout="wide"
    )
    
    st.title("🐳 Docker Build Waterfall Viewer")
    st.markdown("""
    Upload your Docker build logs to visualize the build process as an interactive waterfall chart.
    This tool supports both BuildKit and legacy Docker build formats.
    """)
    
    # Sidebar for options
    with st.sidebar:
        st.header("Options")
        show_cached = st.checkbox("Show cached steps", value=True)
        highlight_bottlenecks = st.checkbox("Highlight bottlenecks", value=True)
        bottleneck_threshold = st.slider(
            "Bottleneck threshold (percentile)",
            min_value=50,
            max_value=95,
            value=75,
            step=5,
            help="Steps with duration above this percentile will be marked as bottlenecks"
        )
        
    # File upload
    uploaded_file = st.file_uploader(
        "Choose a Docker build log file",
        type=['log', 'txt'],
        help="Upload a text file containing Docker build output"
    )
    
    # Example logs button
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("Load BuildKit Example"):
            example_content = load_buildkit_example()
            process_logs(example_content, show_cached, highlight_bottlenecks, bottleneck_threshold)
    
    with col2:
        if st.button("Load Legacy Example"):
            example_content = load_legacy_example()
            process_logs(example_content, show_cached, highlight_bottlenecks, bottleneck_threshold)
    
    # Process uploaded file
    if uploaded_file is not None:
        content = uploaded_file.read().decode('utf-8')
        process_logs(content, show_cached, highlight_bottlenecks, bottleneck_threshold)


def process_logs(content: str, show_cached: bool, highlight_bottlenecks: bool, bottleneck_threshold: int):
    """Process log content and display visualization."""
    parser = DockerLogParser()
    
    with st.spinner("Parsing Docker build logs..."):
        steps = parser.parse_logs(content)
        
    if not steps:
        st.error("No build steps found in the log file. Please check the format.")
        return
        
    # Filter cached steps if requested
    if not show_cached:
        steps = [s for s in steps if not s.is_cached]
        
    # Detect parallelism
    parallel_groups = parser.detect_parallelism(steps)
    
    # Identify bottlenecks
    bottlenecks = parser.identify_bottlenecks(steps, bottleneck_threshold) if highlight_bottlenecks else []
    
    # Display statistics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Steps", len(steps))
    with col2:
        cached_count = len([s for s in steps if s.is_cached])
        st.metric("Cached Steps", cached_count)
    with col3:
        total_duration = sum(s.duration or 0 for s in steps if not s.is_cached)
        st.metric("Total Build Time", f"{total_duration:.2f}s")
    with col4:
        st.metric("Bottlenecks", len(bottlenecks))
    
    # Create visualization
    st.subheader("Build Waterfall Chart")
    
    visualizer = BuildWaterfallVisualizer()
    fig = visualizer.create_waterfall_chart(steps, parallel_groups, bottlenecks)
    visualizer.add_statistics_panel(steps)
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Show bottlenecks detail
    if bottlenecks:
        st.subheader("🚨 Bottleneck Analysis")
        st.markdown("These steps take significantly longer than others and may benefit from optimization:")
        
        for bottleneck in sorted(bottlenecks, key=lambda x: x.duration or 0, reverse=True):
            with st.expander(f"{bottleneck.step_id} - {bottleneck.duration:.2f}s"):
                st.code(bottleneck.description)
                if parallel_groups.get(bottleneck.step_id):
                    st.info(f"Runs in parallel with: {', '.join(parallel_groups[bottleneck.step_id])}")
    
    # Show parallel execution info
    if parallel_groups:
        st.subheader("⚡ Parallel Execution")
        st.markdown("These steps run in parallel:")
        
        # Group parallel steps
        processed = set()
        for step_id, parallel_with in parallel_groups.items():
            if step_id not in processed:
                group = {step_id} | set(parallel_with)
                processed.update(group)
                st.write(f"• {', '.join(sorted(group))}")
    
    # Detailed step information
    with st.expander("📋 Detailed Step Information"):
        step_data = []
        for step in steps:
            step_data.append({
                "Step ID": step.step_id,
                "Description": step.description[:80] + "..." if len(step.description) > 80 else step.description,
                "Duration (s)": f"{step.duration:.2f}" if step.duration else "N/A",
                "Cached": "✓" if step.is_cached else "✗",
                "Type": step.step_type
            })
        st.dataframe(step_data)


def load_buildkit_example() -> str:
    """Load example BuildKit format logs."""
    return """#1 [internal] load build definition from Dockerfile
#1 transferring dockerfile: 32B done
#1 DONE 0.0s

#2 [internal] load .dockerignore
#2 transferring context: 2B done
#2 DONE 0.0s

#3 [internal] load metadata for docker.io/library/python:3.9-slim
#3 DONE 1.2s

#4 [stage-0 1/6] FROM docker.io/library/python:3.9-slim@sha256:abc123
#4 CACHED

#5 [internal] load build context
#5 transferring context: 10.24kB done
#5 DONE 0.1s

#6 [stage-0 2/6] WORKDIR /app
#6 CACHED

#7 [stage-0 3/6] COPY requirements.txt .
#7 DONE 0.2s

#8 [stage-0 4/6] RUN pip install --no-cache-dir -r requirements.txt
#8 0.542 Collecting flask==2.0.1
#8 1.234 Downloading Flask-2.0.1-py3-none-any.whl (94 kB)
#8 2.156 Installing collected packages: flask
#8 DONE 3.5s

#9 [stage-0 5/6] COPY . .
#9 DONE 0.3s

#10 [stage-0 6/6] RUN python -m compileall .
#10 0.234 Compiling './app.py'...
#10 0.567 Compiling './utils.py'...
#10 DONE 1.2s

#11 exporting to image
#11 exporting layers
#11 exporting layers 2.1s done
#11 writing image sha256:def456
#11 writing image sha256:def456 done
#11 DONE 2.3s"""


def load_legacy_example() -> str:
    """Load example legacy format logs."""
    return """Step 1/8 : FROM python:3.9-slim
 ---> Using cache
 ---> abc123def456
Step 2/8 : WORKDIR /app
 ---> Using cache
 ---> 123456abcdef
Step 3/8 : COPY requirements.txt .
 ---> 234567bcdef0
Step 4/8 : RUN pip install --no-cache-dir -r requirements.txt
 ---> Running in 345678cdef01
Collecting flask==2.0.1
  Downloading Flask-2.0.1-py3-none-any.whl (94 kB)
Successfully installed flask-2.0.1
Removing intermediate container 345678cdef01
 ---> 456789def012
Step 5/8 : COPY . .
 ---> 567890ef0123
Step 6/8 : ENV FLASK_APP=app.py
 ---> Running in 678901f01234
Removing intermediate container 678901f01234
 ---> 789012012345
Step 7/8 : EXPOSE 5000
 ---> Running in 890123123456
Removing intermediate container 890123123456
 ---> 901234234567
Step 8/8 : CMD ["flask", "run", "--host=0.0.0.0"]
 ---> Running in 012345345678
Removing intermediate container 012345345678
 ---> 123456456789
Successfully built 123456456789
Successfully tagged myapp:latest"""


if __name__ == "__main__":
    main()