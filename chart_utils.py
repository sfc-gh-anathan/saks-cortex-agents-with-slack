import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
import os
import requests
import time

# Set Matplotlib backend for server-side generation
matplotlib.use('Agg')

# --- Common Plotting Parameters ---
# Define consistent font sizes for better readability
LABEL_FONTSIZE = 16
TITLE_FONTSIZE = 20
TICK_FONTSIZE = 14
LEGEND_FONTSIZE = 14
PIE_TEXT_FONTSIZE = 14 # Specific for text on pie slices

# Define colors for a white background theme
TEXT_COLOR = 'black'
BACKGROUND_COLOR = 'white'
GRID_COLOR = 'lightgray'

# --- Chart Selection and Plotting Functions ---

def select_and_plot_chart(df, app_client):
    """
    Analyzes the DataFrame and determines the best chart type to plot.
    Passes app_client to charting functions for Slack upload.
    Returns the URL of the uploaded chart image or None if no chart can be generated.
    """
    chart_img_url = None
    if len(df.columns) < 2:
        print("DataFrame has less than 2 columns, skipping chart generation.")
        return None

    # --- Chart Selection Priority (from most specific to most general) ---

    # 1. Multi-Line Chart (ideal for Time-Series with Categories: Date, Category, Numeric - 3+ columns)
    if len(df.columns) >= 3 and \
       pd.api.types.is_datetime64_any_dtype(df.iloc[:, 0]) and \
       (pd.api.types.is_string_dtype(df.iloc[:, 1]) or pd.api.types.is_categorical_dtype(df.iloc[:, 1])) and \
       pd.api.types.is_numeric_dtype(df.iloc[:, 2]):
        try:
            chart_img_url = plot_multi_line_chart(df, df.columns[0], df.columns[2], df.columns[1], app_client)
            print("Generated Multi-Line Chart.")
            return chart_img_url
        except Exception as e:
            error_info = f"{type(e).__name__}: {e}"
            print(f"Warning: Could not generate Multi-Line Chart: {error_info}")

    # 2. Scatter Plot (ideal for Relationship: Numeric vs. Numeric - 2+ columns)
    if len(df.columns) >= 2 and \
       pd.api.types.is_numeric_dtype(df.iloc[:, 0]) and \
       pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
        try:
            # If there's a third categorical column, use it for color-coding
            if len(df.columns) >= 3 and \
               (pd.api.types.is_string_dtype(df.iloc[:, 2]) or pd.api.types.is_categorical_dtype(df.iloc[:, 2]) or pd.api.types.is_numeric_dtype(df.iloc[:, 2])):
                chart_img_url = plot_scatter_chart(df, df.columns[0], df.columns[1], app_client, df.columns[2])
                print("Generated Grouped Scatter Chart.")
            else:
                chart_img_url = plot_scatter_chart(df, df.columns[0], df.columns[1], app_client)
                print("Generated Simple Scatter Chart.")
            return chart_img_url
        except Exception as e:
            error_info = f"{type(e).__name__}: {e}"
            print(f"Warning: Could not generate Scatter Chart: {error_info}")

    # 3. Simple Line Chart (ideal for Time-Series: Date vs. Numeric - exactly 2 columns)
    if len(df.columns) == 2 and \
       pd.api.types.is_datetime64_any_dtype(df.iloc[:, 0]) and \
       pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
        try:
            chart_img_url = plot_line_chart(df, df.columns[0], df.columns[1], app_client)
            print("Generated Simple Line Chart.")
            return chart_img_url
        except Exception as e:
            error_info = f"{type(e).__name__}: {e}"
            print(f"Warning: Could not generate Simple Line Chart: {error_info}")

    # 4. Pie Chart (for Proportions: Category vs. Numeric, limited categories - exactly 2 columns)
    if len(df.columns) == 2 and \
       pd.api.types.is_numeric_dtype(df.iloc[:, 1]) and \
       (pd.api.types.is_string_dtype(df.iloc[:, 0]) or pd.api.types.is_categorical_dtype(df.iloc[:, 0])) and \
       len(df.iloc[:, 0].unique()) <= 10: # Limit categories for readability
        try:
            chart_img_url = plot_pie_chart(df, app_client)
            print("Generated Pie Chart.")
            return chart_img_url
        except Exception as e:
            error_info = f"{type(e).__name__}: {e}"
            print(f"Warning: Could not generate Pie Chart: {error_info}")

    # 5. Bar Chart (General comparison: Category/Time vs. Numeric - 2+ columns)
    # This acts as a fallback for 2-column data that isn't a pie or simple line.
    if len(df.columns) >= 2 and pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
        if not pd.api.types.is_numeric_dtype(df.iloc[:, 0]) or pd.api.types.is_datetime64_any_dtype(df.iloc[:, 0]):
            try:
                chart_img_url = plot_bar_chart(df, app_client)
                print("Generated Bar Chart.")
                return chart_img_url
            except Exception as e:
                error_info = f"{type(e).__name__}: {e}"
                print(f"Warning: Could not generate Bar Chart: {error_info}")
    
    print("Data not suitable for any recognized chart type.")
    return None

def plot_pie_chart(df, app_client):
    """Generates a pie chart for categorical vs. numeric data."""
    plt.figure(figsize=(10, 7), facecolor=BACKGROUND_COLOR)

    if not pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
        raise TypeError(f"Second column '{df.columns[1]}' is not numeric for pie chart values.")
    
    if pd.api.types.is_datetime64_any_dtype(df.iloc[:, 0]):
        raise TypeError(f"First column '{df.columns[0]}' is a datetime and not suitable as pie chart labels.")

    if len(df.iloc[:, 0].unique()) > 10:
        print("Too many categories for a pie chart. Consider a bar chart instead.")
        raise ValueError("Too many categories for pie chart.")

    plt.pie(df[df.columns[1]],
            labels=df[df.columns[0]],
            autopct='%1.1f%%',
            startangle=90,
            colors=plt.cm.Set3.colors, # More vibrant discrete colormap
            textprops={'color':TEXT_COLOR, 'fontsize': PIE_TEXT_FONTSIZE})

    plt.axis('equal')
    plt.gca().set_facecolor(BACKGROUND_COLOR)
    plt.title(f'Distribution of {df.columns[1]} by {df.columns[0]}', color=TEXT_COLOR, fontsize=TITLE_FONTSIZE)
    plt.tight_layout()

    file_path_jpg = 'pie_chart.jpg'
    plt.savefig(file_path_jpg, format='jpg')
    file_size = os.path.getsize(file_path_jpg)
    plt.clf() # Clear the current figure
    plt.close() # Close the figure to free memory

    return upload_chart_to_slack(file_path_jpg, file_size, app_client)

def plot_bar_chart(df, app_client):
    """Generates a bar chart for categorical/time vs. numeric data."""
    plt.figure(figsize=(12, 7), facecolor=BACKGROUND_COLOR)
    
    x_col = df.columns[0]
    y_col = df.columns[1]

    if not pd.api.types.is_numeric_dtype(df[y_col]):
        raise TypeError(f"Second column '{y_col}' is not numeric for bar chart values.")

    if pd.api.types.is_datetime64_any_dtype(df[x_col]):
        df_sorted = df.sort_values(by=x_col)
        x_values = df_sorted[x_col].dt.strftime('%Y-%m-%d')
        y_values = df_sorted[y_col]
    else:
        df_sorted = df.sort_values(by=y_col, ascending=False)
        x_values = df_sorted[x_col]
        y_values = df_sorted[y_col]

    plt.bar(x_values, y_values, color='#1f77b4') # Standard Matplotlib blue

    plt.xlabel(x_col, color=TEXT_COLOR, fontsize=LABEL_FONTSIZE)
    plt.ylabel(y_col, color=TEXT_COLOR, fontsize=LABEL_FONTSIZE)
    plt.title(f'{y_col} by {x_col}', color=TEXT_COLOR, fontsize=TITLE_FONTSIZE)
    plt.xticks(rotation=45, ha='right', color=TEXT_COLOR, fontsize=TICK_FONTSIZE)
    plt.yticks(color=TEXT_COLOR, fontsize=TICK_FONTSIZE)
    plt.grid(axis='y', linestyle='--', alpha=0.0, color=GRID_COLOR) # Removed y-axis grid for cleaner look
    plt.gca().set_facecolor(BACKGROUND_COLOR)
    
    # Hide top and right spines for a cleaner look
    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color(GRID_COLOR)
    ax.spines['left'].set_color(GRID_COLOR)

    plt.tight_layout()

    file_path_jpg = 'bar_chart.jpg'
    plt.savefig(file_path_jpg, format='jpg')
    file_size = os.path.getsize(file_path_jpg)
    plt.clf() # Clear the current figure
    plt.close() # Close the figure to free memory

    return upload_chart_to_slack(file_path_jpg, file_size, app_client)

def plot_line_chart(df, x_col, y_col, app_client):
    """Generates a simple line chart for time-series data (Date vs. Numeric)."""
    plt.figure(figsize=(12, 7), facecolor=BACKGROUND_COLOR)

    if not pd.api.types.is_datetime64_any_dtype(df[x_col]):
        raise TypeError(f"First column '{x_col}' is not a datetime for line chart.")
    if not pd.api.types.is_numeric_dtype(df[y_col]):
        raise TypeError(f"Second column '{y_col}' is not numeric for line chart values.")

    df_sorted = df.sort_values(by=x_col)

    plt.plot(df_sorted[x_col], df_sorted[y_col], marker='o', color='#2ca02c', linestyle='-') # Standard Matplotlib green

    plt.xlabel(x_col, color=TEXT_COLOR, fontsize=LABEL_FONTSIZE)
    plt.ylabel(y_col, color=TEXT_COLOR, fontsize=LABEL_FONTSIZE)
    plt.title(f'{y_col} Over Time', color=TEXT_COLOR, fontsize=TITLE_FONTSIZE)
    plt.xticks(rotation=45, ha='right', color=TEXT_COLOR, fontsize=TICK_FONTSIZE)
    plt.yticks(color=TEXT_COLOR, fontsize=TICK_FONTSIZE)
    plt.grid(True, linestyle='--', alpha=0.7, color=GRID_COLOR)
    plt.gca().set_facecolor(BACKGROUND_COLOR)

    # Hide top and right spines for a cleaner look
    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color(GRID_COLOR)
    ax.spines['left'].set_color(GRID_COLOR)

    plt.tight_layout()

    file_path_jpg = 'line_chart.jpg'
    plt.savefig(file_path_jpg, format='jpg')
    file_size = os.path.getsize(file_path_jpg)
    plt.clf() # Clear the current figure
    plt.close() # Close the figure to free memory

    return upload_chart_to_slack(file_path_jpg, file_size, app_client)

def plot_multi_line_chart(df, x_col, y_col, group_col, app_client):
    """Generates a multi-line chart tracking multiple series over time."""
    plt.figure(figsize=(14, 8), facecolor=BACKGROUND_COLOR)

    if not pd.api.types.is_datetime64_any_dtype(df[x_col]):
        raise TypeError(f"X-axis column '{x_col}' is not datetime for multi-line chart.")
    if not pd.api.types.is_numeric_dtype(df[y_col]):
        raise TypeError(f"Y-axis column '{y_col}' is not numeric for multi-line chart.")
    if not pd.api.types.is_string_dtype(df[group_col]) and not pd.api.types.is_categorical_dtype(df[group_col]):
        if not pd.api.types.is_numeric_dtype(df[group_col]):
            raise TypeError(f"Group column '{group_col}' is not categorical (string/numeric/categorical) for multi-line chart.")

    df_sorted = df.sort_values(by=x_col)
    df_sorted[group_col] = df_sorted[group_col].astype(str) # Ensure group column is string for legend labels
    
    unique_groups = df_sorted[group_col].unique()
    num_colors = len(unique_groups)

    # Use vibrant discrete colormaps
    colors = plt.cm.get_cmap('Dark2', num_colors) # 'Dark2' for up to 8 categories
    if num_colors > 8: # Fallback for more categories
        colors = plt.cm.get_cmap('plasma', num_colors)

    for i, group_name in enumerate(unique_groups):
        subset = df_sorted[df_sorted[group_col] == group_name]
        plt.plot(subset[x_col], subset[y_col], marker='o', label=group_name, color=colors(i))

    plt.xlabel(x_col, color=TEXT_COLOR, fontsize=LABEL_FONTSIZE)
    plt.ylabel(y_col, color=TEXT_COLOR, fontsize=LABEL_FONTSIZE)
    plt.title(f'{y_col} Over Time by {group_col}', color=TEXT_COLOR, fontsize=TITLE_FONTSIZE)
    plt.xticks(rotation=45, ha='right', color=TEXT_COLOR, fontsize=TICK_FONTSIZE)
    plt.yticks(color=TEXT_COLOR, fontsize=TICK_FONTSIZE)
    plt.legend(title=group_col, bbox_to_anchor=(1.02, 1), loc='upper left', frameon=False, fontsize=LEGEND_FONTSIZE, title_fontsize=LABEL_FONTSIZE, labelcolor=TEXT_COLOR)
    
    plt.grid(True, linestyle='--', alpha=0.7, color=GRID_COLOR)
    plt.gca().set_facecolor(BACKGROUND_COLOR)

    # Hide top and right spines for a cleaner look
    ax = plt.gca()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color(GRID_COLOR)
    ax.spines['left'].set_color(GRID_COLOR)

    plt.tight_layout(rect=[0, 0, 0.85, 1]) # Adjust layout for legend

    file_path_jpg = 'multi_line_chart.jpg'
    plt.savefig(file_path_jpg, format='jpg')
    file_size = os.path.getsize(file_path_jpg)
    plt.clf() # Clear the current figure
    plt.close() # Close the figure to free memory

    return upload_chart_to_slack(file_path_jpg, file_size, app_client)

def plot_scatter_chart(df, x_col, y_col, app_client, group_col=None):
    """Generates a scatter plot to show relationships between two numeric columns, with optional grouping."""
    plt.figure(figsize=(14, 8), facecolor=BACKGROUND_COLOR)
    
    ax = plt.gca()
    # Remove top and right bounding box (spines), keep bottom/left but make them subtle
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color(GRID_COLOR)
    ax.spines['left'].set_color(GRID_COLOR)

    if not pd.api.types.is_numeric_dtype(df[x_col]):
        raise TypeError(f"X-axis column '{x_col}' is not numeric for scatter plot.")
    if not pd.api.types.is_numeric_dtype(df[y_col]):
        raise TypeError(f"Y-axis column '{y_col}' is not numeric for scatter plot.")

    if group_col and (pd.api.types.is_string_dtype(df[group_col]) or pd.api.types.is_categorical_dtype(df[group_col]) or pd.api.types.is_numeric_dtype(df[group_col])):
        unique_groups = df[group_col].unique()
        num_colors = len(unique_groups)
        
        # Use more vibrant discrete colormaps for grouped scatter
        colors = plt.cm.get_cmap('Set1', num_colors) # 'Set1' for up to 9 categories
        if num_colors > 9: # Fallback for more categories
            colors = plt.cm.get_cmap('plasma', num_colors)

        for i, group_name in enumerate(unique_groups):
            subset = df[df[group_col] == group_name]
            plt.scatter(subset[x_col], subset[y_col], label=group_name, color=colors(i), alpha=0.8, s=80) # Increased marker size (s)
        
        plt.legend(title=group_col, bbox_to_anchor=(1.02, 1), loc='upper left', frameon=False, fontsize=LEGEND_FONTSIZE, title_fontsize=LABEL_FONTSIZE, labelcolor=TEXT_COLOR)
        plt.title(f'Relationship between {y_col} and {x_col} by {group_col}', color=TEXT_COLOR, fontsize=TITLE_FONTSIZE)
        plt.tight_layout(rect=[0, 0, 0.85, 1]) # Adjust layout for legend
    else:
        # Simple scatter plot without grouping
        plt.scatter(df[x_col], df[y_col], color='#FF7F0E', alpha=0.8, s=80) # More vibrant orange, increased marker size
        plt.title(f'Relationship between {y_col} and {x_col}', color=TEXT_COLOR, fontsize=TITLE_FONTSIZE)
        plt.tight_layout()

    plt.xlabel(x_col, color=TEXT_COLOR, fontsize=LABEL_FONTSIZE)
    plt.ylabel(y_col, color=TEXT_COLOR, fontsize=LABEL_FONTSIZE)
    plt.xticks(color=TEXT_COLOR, fontsize=TICK_FONTSIZE)
    plt.yticks(color=TEXT_COLOR, fontsize=TICK_FONTSIZE)
    plt.grid(True, linestyle='--', alpha=0.7, color=GRID_COLOR)
    plt.gca().set_facecolor(BACKGROUND_COLOR)

    file_path_jpg = 'scatter_chart.jpg'
    plt.savefig(file_path_jpg, format='jpg')
    file_size = os.path.getsize(file_path_jpg)
    plt.clf() # Clear the current figure
    plt.close() # Close the figure to free memory

    return upload_chart_to_slack(file_path_jpg, file_size, app_client)

def upload_chart_to_slack(file_path_jpg, file_size, app_client):
    """
    Helper function to upload the generated chart image to Slack and return its permalink.
    """
    # NOTE: DEBUG variable is not accessible in this file directly unless passed or re-defined.
    # For now, assuming DEBUG is handled by print statements or not critical for this helper.
    
    file_upload_url_response = app_client.files_getUploadURLExternal(filename=file_path_jpg,length=file_size)
    # if DEBUG: # DEBUG is not directly available here
    #     print(file_upload_url_response)
    file_upload_url = file_upload_url_response['upload_url']
    file_id = file_upload_url_response['file_id']
    with open(file_path_jpg, 'rb') as f:
        response = requests.post(file_upload_url, files={'file': f})

    img_url = None
    if response.status_code != 200:
        print(f"File upload failed: {response.text}") # More informative error
    else:
        response = app_client.files_completeUploadExternal(files=[{"id":file_id, "title":"chart"}])
        # if DEBUG: # DEBUG is not directly available here
        #     print(response)
        img_url = response['files'][0]['permalink']
        time.sleep(2) # Give Slack time to process the image
    
    os.remove(file_path_jpg) # Clean up the local file after upload
    return img_url