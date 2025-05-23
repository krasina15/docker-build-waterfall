import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional
from log_parser import BuildStep


class BuildWaterfallVisualizer:
    """Create interactive Gantt chart visualization for Docker build steps."""
    
    # Color scheme for different step types
    COLOR_SCHEME = {
        'cached': '#90EE90',  # Light green
        'RUN': '#4169E1',     # Royal blue
        'COPY': '#FF8C00',    # Dark orange
        'FROM': '#9370DB',    # Medium purple
        'WORKDIR': '#20B2AA', # Light sea green
        'ENV': '#FFD700',     # Gold
        'ARG': '#FF69B4',     # Hot pink
        'USER': '#8B4513',    # Saddle brown
        'OTHER': '#808080',   # Gray
        'bottleneck': '#DC143C'  # Crimson
    }
    
    def __init__(self):
        self.fig = None
        
    def create_waterfall_chart(self, 
                              steps: List[BuildStep], 
                              parallel_groups: Optional[Dict[str, List[str]]] = None,
                              bottlenecks: Optional[List[BuildStep]] = None) -> go.Figure:
        """Create an interactive Gantt chart showing build steps."""
        if not steps:
            return self._create_empty_chart()
            
        # Prepare data for visualization
        df_data = self._prepare_dataframe(steps, parallel_groups, bottlenecks)
        
        # Create the figure
        self.fig = go.Figure()
        
        # Add traces for each step
        for _, row in df_data.iterrows():
            self._add_step_trace(row)
            
        # Update layout
        self._update_layout(df_data)
        
        return self.fig
    
    def _prepare_dataframe(self, 
                          steps: List[BuildStep], 
                          parallel_groups: Optional[Dict[str, List[str]]],
                          bottlenecks: Optional[List[BuildStep]]) -> pd.DataFrame:
        """Prepare DataFrame for visualization."""
        data = []
        bottleneck_ids = {b.step_id for b in (bottlenecks or [])}
        
        # Assign Y-positions based on parallelism
        y_positions = self._calculate_y_positions(steps, parallel_groups)
        
        for step in steps:
            # Determine color
            if step.step_id in bottleneck_ids:
                color = self.COLOR_SCHEME['bottleneck']
            elif step.is_cached:
                color = self.COLOR_SCHEME['cached']
            else:
                step_type = self._extract_step_type(step.description)
                color = self.COLOR_SCHEME.get(step_type, self.COLOR_SCHEME['OTHER'])
            
            # Create hover text
            hover_text = self._create_hover_text(step, parallel_groups)
            
            data.append({
                'step_id': step.step_id,
                'description': step.description[:50] + '...' if len(step.description) > 50 else step.description,
                'start_time': step.start_time,
                'end_time': step.end_time or step.start_time,
                'duration': step.duration or 0,
                'y_position': y_positions.get(step.step_id, 0),
                'color': color,
                'hover_text': hover_text,
                'is_cached': step.is_cached,
                'is_bottleneck': step.step_id in bottleneck_ids
            })
        
        return pd.DataFrame(data)
    
    def _calculate_y_positions(self, 
                              steps: List[BuildStep], 
                              parallel_groups: Optional[Dict[str, List[str]]]) -> Dict[str, int]:
        """Calculate Y-positions to show parallel steps on different lanes."""
        y_positions = {}
        
        if not parallel_groups:
            # No parallelism info - stack sequentially
            sorted_steps = sorted(steps, key=lambda s: s.start_time)
            for i, step in enumerate(sorted_steps):
                y_positions[step.step_id] = i
        else:
            # Assign lanes based on parallelism
            lanes_in_use = []
            sorted_steps = sorted(steps, key=lambda s: s.start_time)
            
            for step in sorted_steps:
                # Find first available lane
                lane = 0
                for existing_lane, (_, end_time) in enumerate(lanes_in_use):
                    if step.start_time >= end_time:
                        lane = existing_lane
                        break
                else:
                    lane = len(lanes_in_use)
                    lanes_in_use.append((step.step_id, step.end_time))
                
                if lane < len(lanes_in_use):
                    lanes_in_use[lane] = (step.step_id, step.end_time)
                    
                y_positions[step.step_id] = lane
                
        return y_positions
    
    def _extract_step_type(self, description: str) -> str:
        """Extract step type from description."""
        keywords = ['RUN', 'COPY', 'FROM', 'WORKDIR', 'ENV', 'ARG', 'USER', 'ADD', 'EXPOSE']
        
        for keyword in keywords:
            if description.upper().startswith(keyword):
                return keyword
                
        return 'OTHER'
    
    def _create_hover_text(self, 
                          step: BuildStep, 
                          parallel_groups: Optional[Dict[str, List[str]]]) -> str:
        """Create detailed hover text for a step."""
        lines = [
            f"<b>{step.step_id}</b>",
            f"<b>Description:</b> {step.description}",
            f"<b>Start:</b> {step.start_time.strftime('%H:%M:%S.%f')[:-3]}",
            f"<b>Duration:</b> {step.duration:.2f}s" if step.duration else "<b>Duration:</b> N/A",
            f"<b>Type:</b> {step.step_type}",
            f"<b>Layer:</b> {step.layer_info}" if step.layer_info else "",
            f"<b>Cached:</b> {'Yes' if step.is_cached else 'No'}"
        ]
        
        if parallel_groups and step.step_id in parallel_groups:
            parallel_with = ', '.join(parallel_groups[step.step_id])
            lines.append(f"<b>Parallel with:</b> {parallel_with}")
            
        return '<br>'.join(filter(None, lines))
    
    def _add_step_trace(self, row: pd.Series) -> None:
        """Add a trace for a single step."""
        # Create a box shape for the step
        self.fig.add_trace(go.Scatter(
            x=[row['start_time'], row['end_time'], row['end_time'], row['start_time'], row['start_time']],
            y=[row['y_position'] - 0.4, row['y_position'] - 0.4, 
               row['y_position'] + 0.4, row['y_position'] + 0.4, row['y_position'] - 0.4],
            fill='toself',
            fillcolor=row['color'],
            line=dict(color=row['color'], width=1),
            hovertext=row['hover_text'],
            hoverinfo='text',
            name=row['step_id'],
            showlegend=False,
            mode='lines'
        ))
        
        # Add text label
        self.fig.add_annotation(
            x=row['start_time'] + (row['end_time'] - row['start_time']) / 2,
            y=row['y_position'],
            text=row['description'],
            showarrow=False,
            font=dict(size=10),
            xanchor='center',
            yanchor='middle'
        )
    
    def _update_layout(self, df: pd.DataFrame) -> None:
        """Update figure layout."""
        # Calculate time range
        min_time = df['start_time'].min()
        max_time = df['end_time'].max()
        time_buffer = (max_time - min_time) * 0.05
        
        self.fig.update_layout(
            title={
                'text': 'Docker Build Waterfall',
                'font': {'size': 24}
            },
            xaxis=dict(
                title='Time',
                type='date',
                range=[min_time - time_buffer, max_time + time_buffer],
                showgrid=True,
                gridwidth=1,
                gridcolor='LightGray'
            ),
            yaxis=dict(
                title='Build Steps',
                range=[-1, df['y_position'].max() + 1],
                showticklabels=False,
                showgrid=False
            ),
            hovermode='closest',
            height=max(600, 50 * len(df)),
            plot_bgcolor='white',
            showlegend=True
        )
        
        # Add legend items
        legend_items = [
            ('Cached', self.COLOR_SCHEME['cached']),
            ('Running', self.COLOR_SCHEME['RUN']),
            ('Bottleneck', self.COLOR_SCHEME['bottleneck'])
        ]
        
        for i, (label, color) in enumerate(legend_items):
            self.fig.add_trace(go.Scatter(
                x=[None],
                y=[None],
                mode='markers',
                marker=dict(size=10, color=color),
                showlegend=True,
                name=label
            ))
    
    def _create_empty_chart(self) -> go.Figure:
        """Create an empty chart when no data is available."""
        fig = go.Figure()
        fig.add_annotation(
            text="No build steps to display",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=20)
        )
        fig.update_layout(
            title="Docker Build Waterfall",
            xaxis=dict(showgrid=False, showticklabels=False),
            yaxis=dict(showgrid=False, showticklabels=False)
        )
        return fig
    
    def add_statistics_panel(self, steps: List[BuildStep]) -> None:
        """Add a statistics panel to the visualization."""
        if not self.fig or not steps:
            return
            
        # Calculate statistics
        total_steps = len(steps)
        cached_steps = len([s for s in steps if s.is_cached])
        total_duration = sum(s.duration or 0 for s in steps)
        avg_duration = total_duration / len([s for s in steps if s.duration]) if steps else 0
        
        # Add annotations
        stats_text = (
            f"Total Steps: {total_steps} | "
            f"Cached: {cached_steps} | "
            f"Total Time: {total_duration:.2f}s | "
            f"Avg Duration: {avg_duration:.2f}s"
        )
        
        self.fig.add_annotation(
            text=stats_text,
            xref="paper",
            yref="paper",
            x=0.5,
            y=1.05,
            showarrow=False,
            font=dict(size=12),
            xanchor='center'
        )