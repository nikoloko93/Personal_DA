from flask import Flask, render_template, request, redirect, url_for, session, jsonify 
import pandas as pd
from IPython.display import HTML
import numpy as np
import calendar
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
import openai
import os
import time
import re 
import json   
import matplotlib.pyplot as plt  
import plotly.io as pio
import base64  
import io 
import requests
import contextlib
from queue import Queue
import threading
from copy import deepcopy


app = Flask(__name__, static_folder='static')
app.secret_key = 'your_secret_key_here'  # Replace with a secret key for session management

# Set the OpenAI API key
openai.api_key = "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"

# Read login credentials from CSV file in the "data" folder
credentials_df = pd.read_csv('data/login_credentials.csv')
linel_data = pd.read_csv('data/linel_sample.csv')
lms_data =  pd.read_csv('data/lms_sample.csv')

shared_data = Queue()

# Current Month
current_month_str = '2023-06-01'
# Convert the current month string to a datetime object
current_month = datetime.strptime(current_month_str, '%Y-%m-%d')
# Extract the month and year
month = current_month.strftime('%B')  # Full month name (e.g., 'June')
year = current_month.strftime('%Y')    # Year with century as a decimal number (e.g., '2023')
combined_date = f'{month} {year}'
# Calculate the previous month by subtracting one month (30 or 31 days)
previous_month = current_month.replace(day=1) - timedelta(days=1)
previous_month = previous_month.replace(day=1)
# Format the previous month as a string in 'YYYY-MM-DD' format
previous_month_str = previous_month.strftime('%Y-%m-%d')

#------------------------------------------------------------------------
#chat with AI
# Create a global variable to store the conversation history  
conversation_history = []  
  
import contextlib  

def process_df(username, credentials_df):
    name_tl = list(credentials_df[credentials_df['username']==username]['name'])[0]
    df = linel_data[linel_data['supervisor']==name_tl].copy()
    df['RTOdate'] = pd.to_datetime(df['RTOdate'])
    df['month'] = df['RTOdate'].dt.month
    df['year'] = df['RTOdate'].dt.year
    df['month_year'] = df['RTOdate'].dt.to_period('M').dt.to_timestamp()

    return df, name_tl

def extract_and_execute_python_code2(text, exec_globals):
    pattern = r'```python(.*?)```'
    matches = re.findall(pattern, text, re.DOTALL)
    result = []
    type_dat = []

    if matches:
        for match in matches:
            str_buffer = io.StringIO()
            with contextlib.redirect_stdout(str_buffer):
                exec_globals = exec_globals
                exec(match.strip(), exec_globals)
                
            # if there is a string output
            #print_output = str_buffer.getvalue()
            #if print_output:
                #result.append(print_output.strip())

            # Get the last defined variable
            # Remove the '__builtins__' key
            exec_globals.pop('__builtins__', None)
            last_var_key = list(exec_globals.keys())[-1]
            last_var_value = exec_globals[last_var_key]
            if isinstance(last_var_value, pd.DataFrame):
                tab_html = last_var_value.to_html(classes='display', index=False, escape=False)
                result.append(tab_html)
                type_dat.append("df")
                print('df')
            elif isinstance(last_var_value, pd.Series):
                result.append(last_var_value.to_frame().to_html(classes='display', index=False, escape=False))
                type_dat.append("series")
            elif type(last_var_value) == go.Figure:
                # Serialize the Plotly figure to JSON
                fig_json = pio.to_json(last_var_value, validate=False)
                result.append(fig_json)
                type_dat.append("plotly")
            else:
                result.append(str(last_var_value))
                type_dat.append("str")
                print('str')

    return result, type_dat 


@app.route('/')
@app.route('/login', methods=['GET', 'POST'])
def login():
    error_message = None  # Initialize error_message

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Check if the credentials exist in the CSV file
        if (credentials_df['username'] == username).any() and (credentials_df['password'] == password).any():
            # Authentication successful, set a session variable and redirect to the index page
            session['loggedin'] = True
            session['username'] = username

            # Calculate initials of the username and store them in the session
            initials = "".join(part[0].upper() for part in username.split())
            session['initials'] = initials

            return redirect(url_for('index'))

        # Authentication failed, display an error message
        else:
            error_message = 'Invalid username or password. Please try again.'

    # If the request method is GET or authentication failed, render the login form
    return render_template('login.html', error_message=error_message)

@app.route('/logout')
def logout():
    session.pop('loggedin', None)
    session.pop('username', None)
    session.pop('initials', None)  # Clear the saved initials on logout
    return redirect(url_for('login'))

@app.route('/index')
def index():
    # Check if the user is logged in before rendering the index page
    if 'loggedin' in session:
        username = session['username']
        initials = session.get('initials', '')  # Retrieve saved initials
        # DF processing
        df, name_tl = process_df(username, credentials_df)

        # LMS data processing
        df_lms =  lms_data[lms_data['supervisor']==name_tl].copy()
        df_lms['leave_date'] = pd.to_datetime(df_lms['leave_date'])
        df_lms['month'] = df_lms['leave_date'].dt.month
        df_lms['year'] = df_lms['leave_date'].dt.year
        df_lms['month_year'] = df_lms['leave_date'].dt.to_period('M').dt.to_timestamp()
        df_lms.sort_values(['name', 'leave_date'], ascending=True, inplace=True)
        df_lms['date_diff'] = df_lms['leave_date'].diff()
        df_lms['date_diff'] = df_lms['date_diff'].dt.days
        
        df['target_RTO'] = 8
        df['consec_PTO'] = 'No'
        member_count = len(df.name.value_counts())
        df1 = df.groupby(['name', 'month_year']).size().reset_index(name='days_working_onsite')
        df1_a = df1[df1['month_year']==current_month_str].copy()

        month_year_list = list(df['month_year'].unique())
        df_list = []
        for month_year in month_year_list:
            df_here = df_lms[df_lms['month_year'] == month_year]
            df_here_1 = df[df['month_year'] == month_year]

            name_list = list(df_here_1['name'].unique())
            for name in name_list:
                df_here_2 = df_here[df_here['name'] == name]
                df_here_3 = df_here_1[df_here_1['name'] == name]
                pattern_4 = [1,1,1]
                pattern_5 = [1,1,1,1]
                date_diff_list = list(df_here_2['date_diff'])
                count_ones = date_diff_list.count(1)

                if count_ones < 3:
                    pass
                else:
                    pattern_found_5 = False
                    pattern_found_4 = False 
                    for i in range(len(date_diff_list)):
                        if (date_diff_list[i:i+4] == pattern_5):
                            pattern_found_5 = True
                        else:
                            pass
                        if (date_diff_list[i:i+3] == pattern_4): 
                            pattern_found_4 = True
                        else:
                            pass

                    if (pattern_found_5 == True) & (pattern_found_4 == True):
                        df_here_3['target_RTO'] = 6
                        df_here_3['consec_PTO'] = '5 PTO Days'
                    else:
                        df_here_3['target_RTO'] = 7
                        df_here_3['consec_PTO'] = '4 PTO Days'
                df_list.append(df_here_3)

        df_new = pd.concat(df_list)

        df_filtered = df_new[['name', 'month_year', 'target_RTO', 'consec_PTO']].copy()
        df_filtered.drop_duplicates(keep='last', inplace=True)

        df_filtered_merged = df1_a.merge(df_filtered, on=['name', 'month_year'], how='left')
        df_filtered_merged['req_rto_days'] = df_filtered_merged['target_RTO'] - df_filtered_merged['days_working_onsite']
        df_filtered_merged['req_rto_days'] = np.where((df_filtered_merged['days_working_onsite'] > 8), 0, df_filtered_merged['req_rto_days'])

        date = month + " 24," + year
        date2 = month + " " + year
        tot_RTO_cur = sum(df1_a['days_working_onsite'])
        # Calculate the ratio of tot_RTO_cur to target
        #target = len(df['employeenumber'].value_counts())*8
        target = df_filtered_merged['target_RTO'].sum()
        ratio = (tot_RTO_cur / target) * 100  # Multiply by 100 to get a percentage
        mean_man_hour = round(df[df['month_year'] == current_month_str]['man_hour'].mean(),1)
        mean_man_hour_percentage = (mean_man_hour / 9) * 100  # Adjust the maximum value as needed
        # average rto days
        mean_rto_days = round(tot_RTO_cur/member_count, 1)
        num_members_with_rto = len(df1_a)
        # members with <4 man hour for current month
        #cnt_mem_ls4MH = len(set(df[(df['month_year']==current_month_str) & (df['man_hour']<=4)].name))
        
        # Chart 1
        # insert RTO target for current month

        fig_chart_1 = go.Figure()
        fig_chart_1.add_trace(go.Bar(
            x=df_filtered_merged['days_working_onsite'],    
            y=df_filtered_merged['name'],
            orientation = 'h',
            name='RTO',
            #marker=dict(color='#8223D2'),  # Violet           
            marker=dict(color='#6EFAC3'),   # Green
        ))

        fig_chart_1.add_trace(go.Bar(
            x=df_filtered_merged['req_rto_days'],
            y=df_filtered_merged['name'],
            orientation = 'h',
            name='Required',
            #marker=dict(color='#6B8BFF'),  # Blue
            marker=dict(color='#A5AAAF'),   # Grey
        ))

        fig_chart_1.update_layout(
            barmode='stack', 
            legend=dict(x=.005, y=-0.35),
            title=f'<b style="font-family: Arial; text-align: center;">RTO Days vs RTO Target per Member for {date2}</b>'
        )
        fig_chart_1.update_xaxes(range=[0,8])
        fig_chart_1.update_xaxes(title_text='RTO Days')
        fig_chart_1.update_layout({"plot_bgcolor": "rgba(0,0,0,0)", "paper_bgcolor": '#f7faf5'})
        fig_chart_1_html = fig_chart_1.to_html()

        # Chart 2
        df2 = df.groupby(['name', 'month_year'])['man_hour'].mean().reset_index()
        df2_sum = df.groupby(['name', 'month_year'])['man_hour'].sum().reset_index(name='sum_man_hours')
        df2['man_hour'] = df2['man_hour'].round(1)

        df2_a = df2[df2['month_year']==current_month_str]
        

        fig_chart_2 = px.bar(
            df2_a,
            x='man_hour',  # Switch to 'x' for the data values
            y='name',      # Switch to 'y' for the categories/labels
            text='man_hour', 
            title=f'<b style="font-family: Arial; text-align: center;">Average RTO Man Hours per Member for {date2}</b>',
            orientation='h',  # Set orientation to 'h' for horizontal bars
        )
        fig_chart_2.update_xaxes(title_text='RTO Man Hour')
        fig_chart_2.update_yaxes(title_text='')  # Hide y-axis tick labels
        #fig_chart_2.update_traces(marker_color = '#8223D2')    # Violet
        fig_chart_2.update_traces(marker_color = '#6EFAC3') # Green
        fig_chart_2.update_layout({"plot_bgcolor": "rgba(0,0,0,0)", "paper_bgcolor": '#f7faf5'})
        fig_chart_2_html = fig_chart_2.to_html()
        
        # Table 1
        df3 = df[df['man_hour']<4].groupby(['name', 'month_year']).size().reset_index(name='Count RTO Days with < 4H')
        df_actuals = df1.merge(df2, on=['name', 'month_year'])
        df_actuals = df_actuals.merge(df_filtered, on=['name', 'month_year'], how='left')
        df_actuals = df_actuals.merge(df3, on=['name', 'month_year'], how='left')
        df_actuals['Count RTO Days with < 4H'].fillna(0, inplace=True)
        df_actuals['sum_target_man_hrs'] = df_actuals['target_RTO'] *4
        df_actuals = df_actuals.merge(df2_sum, on=['name', 'month_year'], how='left')
        df_actuals['count_diff'] = df_actuals['days_working_onsite'] - df_actuals['Count RTO Days with < 4H']
        #compliance tagging
        # Create a new column 'Compliance' based on conditions

        #df_actuals['Compliance'] = ['Compliant' if (count_rto >= rto_target) and (sum_man_hours >= sum_target_man_hrs) and (count_less_than_4 == 0) else 'Non-compliant' for count_rto, rto_target, sum_man_hours, sum_target_man_hrs, count_less_than_4 in zip(df_actuals['days_working_onsite'], df_actuals['target_RTO'], df_actuals['sum_man_hours'], df_actuals['sum_target_man_hrs'],  df_actuals['Count RTO Days with < 4H'])]
        df_actuals['Compliance'] = ['Compliant' if (count_rto >= rto_target) and (count_diff >= rto_target)  else 'Non-compliant' for count_rto, rto_target, count_diff in zip(df_actuals['days_working_onsite'], df_actuals['target_RTO'], df_actuals['count_diff'])]
        
        df_actuals_2 = df_actuals[df_actuals['month_year'] == current_month]
        non_compliant_members_current = len(df_actuals_2[df_actuals_2['Compliance'] == 'Non-compliant'])

        #df_actuals['rto_days_target'] = 8
        # Create a dictionary with old column names as keys and new column names as values
        column_rename_mapping = {
            'name': 'Employee Name',
            'month_year': 'Month Year',
            'days_working_onsite': 'Actual RTO Days',
            'man_hour': 'Mean RTO Man Hour',
            'target_RTO': 'RTO Days Target', 
            'Count RTO Days with < 4H' : 'RTO Days with < 4 MH',
            'consec_PTO' : 'Consecutive PTOs'
            # Add more columns as needed
        }

        # Use the rename method with the dictionary
        df_actuals.rename(columns=column_rename_mapping, inplace=True)
        df_actuals = df_actuals[['Employee Name', 'Month Year', 'Actual RTO Days', 'RTO Days Target', 'Consecutive PTOs', 'Mean RTO Man Hour', 'RTO Days with < 4 MH', 'Compliance']]
        #df_actuals = df_actuals[['Employee Name', 'Month Year', 'Actual RTO Days', 'RTO Days Target', 'Consecutive PTOs', 'RTO Days with < 4 MH', 'Compliance']]
        #df_actuals = df_actuals['Compliance'].apply(color_compliance)
        df_actuals_json = df_actuals.to_json(orient='records')
        session['df_actuals'] = df_actuals_json  # Store df_actuals in the session
        df_actuals_html = df_actuals.to_html(classes='display', 
                                             index=False, 
                                             escape=False,
                                             table_id="data_panda", 
                                             justify="center")


        return render_template('index.html', username=username, initials=initials, 
                               tot_RTO_cur=tot_RTO_cur, ratio = ratio, target=target, date=date,
                               mean_man_hour=mean_man_hour, mean_man_hour_percentage = mean_man_hour_percentage, fig_chart_1_html=fig_chart_1_html, 
                               fig_chart_2_html=fig_chart_2_html, df_actuals_html=df_actuals_html, mean_rto_days=mean_rto_days,
                               member_count=member_count, num_members_with_rto=num_members_with_rto,
                               non_compliant_members_current=non_compliant_members_current)
    else:
        return redirect(url_for('login')) 


  
@app.route('/process_message', methods=['POST'])  
def process_message():  
    data = request.get_json()  
    user_message = data['message'] 

    username = session['username']
    #initials = session.get('initials', '')  # Retrieve saved initials
    # DF processing
    RTOdata, tl= process_df(username, credentials_df)
    Comp_df = pd.read_json(session['df_actuals'])
    lms_df =  lms_data[lms_data['supervisor']==tl].copy()
    lms_df['leave_date']= pd.to_datetime(lms_df['leave_date'])

    Comp_df['Month Year'] = pd.to_datetime(Comp_df['Month Year'] / 1000, unit='s')
    exec_globals = {'RTOdata': RTOdata, 'Comp_df':Comp_df, 'lms_df':lms_df}
    #'Employee Name', 'Month Year', 'Actual RTO Days', 'RTO Days Target', 'Consecutive PTOs', 'Mean RTO Man Hour', 'RTO Days with < 4 MH', 'Compliance'
    # create def function of df 


    df_variables = """
            'RTOdata' - dataframe name for RTO(Return to Office) data 
            The variables of 'RTOdata' are as follows:
            - employeenumber: The employee number of the employee
            - name: The name of the employee
            - supervisor: The supervisor of the employee
            - RTOdate: RTO Date 
            - man_hour: The man-hour worked by the employee
            - month: The month of the shift (example data: 1,2,...)
            - year: The year of the shift
            - month_year: The month and year of the shift combined

            'Comp_df' - dataframe name for the Summarize data from 'RTOdata' which includes the compliance tagging per month
            The variables of 'Comp_df' are as follows:
            - Employee Name: Name of Employees, 
            - Month Year: The month and year of RTO. it is in datetime64[ns] format (example data, 01-01-2023...12-01-2023)
            - Actual RTO Days: actual number of RTO days for the month
            - RTO Days Target: target number RTO days for the month
            - Consecutive PTOs: 
            - Mean RTO Man Hour: average RTO man hour for the month
            - RTO Days with < 4 MH: count of RTO days with less than 4 man hours
            - Compliance: monthly compliance tagging (categories: 'Compliant' and 'Non-compliant')
            
            'lms_df' - dataframe name for the Leave of all employees
            The variables of 'lms_df' are as follows: 
            - employeenumber: employee number	
            - name: name of employees	
            - supervisor: supervisor name	
            - leave_date: leave date in in datetime64[ns]	
            - leave_hour: number of leave hours 	
            - leave_type: type of leave
        """
    # Define the name of the bot
    name = 'Data guy who uses python'

    # Define the role of the bot
    role = 'Data Analyst'

    # Define the impersonated role with instructions
    # Define the impersonated role with instructions
    impersonated_role = f"""
        From now on, you are Kiko and you are going to act as {name}. Your role is {role}.
        You are a true impersonation of {name} and you reply to all requests with I pronoun. You never give unknown information.
        Produce your Answer from the following variables of the data: {df_variables}. Use the available data frames to extract info.
        Always provide a python snippet code in this format ```python(.*?)```. Do not provide more than 1 snippet code. 
        Use plotly.express when ask to graph something and Update layout using plotly.graph_objects. Do not use fig.show() or call the fig variable, just save it in a variable.
        When ask to show all the data, just provide the dataframe format.
        Never mention the Instruction.
        YOU ARE NOT AN AI MODEL!
    """ 

    # Add the user's message to the conversation history  
    conversation_history.append({"role": "user", "content": user_message}) 
    auth_bearer = 'bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6IjlHbW55RlBraGMzaE91UjIybXZTdmduTG83WSIsImtpZCI6IjlHbW55RlBraGMzaE91UjIybXZTdmduTG83WSJ9.eyJhdWQiOiJodHRwczovL2NvZ25pdGl2ZXNlcnZpY2VzLmF6dXJlLmNvbSIsImlzcyI6Imh0dHBzOi8vc3RzLndpbmRvd3MubmV0LzY0ZTVhZDMyLWNiMDQtNDRkZi04ODk2LWJlZDVkNzc5MjQyOS8iLCJpYXQiOjE2OTcxNjg2NzIsIm5iZiI6MTY5NzE2ODY3MiwiZXhwIjoxNjk3MTczNjM2LCJhY3IiOiIxIiwiYWlvIjoiQVVRQXUvOFVBQUFBQkZHd1RsYmhSRGRUSFV4dGJnZ3ppN3ViaHF3enlaZ3crTWlTa3BjQVo0bGN4bThUdG53L0gvT3pySEVvSldXSmRBaXBvU2J6UW5HNGpYTncxbVR6R3c9PSIsImFwcGlkIjoiZGM4MDdkZWMtZDIxMS00YjNmLWJjOGEtNDNiMzQ0M2M0ODc0IiwiYXBwaWRhY3IiOiIwIiwiZGV2aWNlaWQiOiI0Y2M1ZWJmNy1kNjdjLTRiOTUtODJmZi1lNGNjYjNlYTNjMGYiLCJmYW1pbHlfbmFtZSI6IlJhbWFsIiwiZ2l2ZW5fbmFtZSI6Ik5pa2tvIiwiZ3JvdXBzIjpbIjA0OTliNDAzLWJlY2EtNDc3Mi1iYmVkLWNmYjY4Zjg3ZWJlNCIsImJmOTdlOTA1LWM0ZjctNGU2OC04ZGM4LWNmNjZjOTYyYWM2MyIsIjM0YmU5MzBjLTVlYjMtNDkxNi1hNWJjLWZlZjAwM2I2ZjY3YiIsIjQwNDE2NjBkLTBmOWUtNDdhZC04OGJhLWNhN2RhMDBhOWVlMiIsIjZjYjBhYTBlLTU5Y2QtNDRlNS1iNjlhLWQ2MjMyNjZmNjNlNCIsIjMwMGVmYTE5LWNkNWQtNDk2YS05ZDc2LWVmYTljNTU5NmFjZCIsIjQ4N2FmMTFkLTBiNGYtNDZmNS1iMmFjLWEzM2NhZGE4MjA4YyIsIjg5OWFmNjIwLTllZjEtNGE2Yy1hOGI1LThjM2NiNjBhYjg0MyIsIjlhZTA1ZDIyLWYzZWMtNGRkYS04MDk5LWU4YTJkMDU0NmE1MSIsIjAyNDA2YjI4LTNhZWEtNGQzZi04ZWU4LWIzNjg4NjgyNTRjNiIsIjdiM2IxZjJjLWY4NmEtNDU3MS04ZDNlLTRjYTc5MWNjZDAzZCIsIjFlMDA1NDJmLTRiOTktNDMzZi1hNTVmLTdmN2U5MDNmOGUzMyIsImMxOTkzOTMxLWJlZTUtNDhmMS1iODZjLTJjMTg0MmI0ODU5MyIsImI4MmVjYTMxLTVhYTQtNDA5OC1hM2FjLWVmNWYxYjdhMWFlMiIsIjVjMTMxNTMyLTc3MmMtNDM0Ny04OWE3LTVmYzQ2MTgwMTdmOSIsImRlZGU3OTMzLWE0NDgtNGFmMC1hOWUxLWM2OTkwMDgwYmZmYiIsIjA0MzJjODM5LTQ4NjgtNDE4OC04OTQyLTljNzdmMTQ2ODI5OSIsIjI3MDEyNTNiLTIyOWEtNDQzZi04MzEyLWJhYWJmMmFmNWRhNSIsIjg2YWExYTQ2LTE4MDItNGUyMy1iM2IxLTdkZTgyOWI1YmMzNyIsIjVmYzE4NjRiLTNjNDgtNGJhZS1iMGQ0LTE5NTkwZDY1MWY4NCIsImI2YjE1NDRmLTgyNjAtNDM2NS1iODYxLWRiYTBlMjBkMzM4NiIsIjNlOTEyMzUwLTNlZDktNDFiNy1hMGUzLTY5YmJkNDRhNDg0NyIsIjRlNzIxNjU0LWE4ZWQtNDZiZi1iNjM4LWRiOTM3NzhlNzJkOSIsIjUzYjkwMTU5LTNkZmUtNDNiMi1hZjlmLWE5YjFmOTJmYWQ1YiIsImExNWM0MTViLWUxODYtNDA2NS1iZmYwLTMyNmY2ZTJhYjQ2ZCIsIjc2NzBmNDVkLTRhYjYtNDU1Ni1iYjZjLTE0NGY3YzEwNjliYyIsIjllMGM4ZTVmLTExYTQtNDAzYS04MjJhLWJlNWJhZmJiZmExYSIsImNiMTMzMTYxLWQ5MjMtNDYxOS04MTY3LWRiMWZlOWZjYzBiZCIsImIyMTZhYjYyLTc0YTYtNGU0OC1iMzc2LWI5ZGU2ZTdkY2QyZiIsImY1NzQwMjYzLWNkMmYtNDI3ZC05MWMyLWRkMmE0ZDI3NWQ3OCIsIjgwZDFkMjY5LTJkYzQtNDM0Yy1iMTk0LThhNzIyNjA0MjI0ZSIsImU3N2M3NjcxLWYwMTgtNGE4Mi1hN2U0LWI5MmU5NThhY2U0NiIsIjhjNmU3Yjc4LTJiZmYtNDlmZC04ZmNlLTJmOGE2ZDdiZWE3OCIsIjYzYTA4ZTdhLThmNzMtNDVhMy1iN2JiLTgzMGNlNzU2NDE0OSIsIjkzM2I2ZTgxLTlhYmMtNGRjNy04M2IyLTNiZTliMmJhZjkzNSIsImY3YWMxNDgzLWQ2MmItNDgyNy04MmExLTdlMTBlNWI5MjEyZSIsIjMzNjNkNzg0LThkNDMtNGY4Yy1hNjliLWRkNmM3Y2M0ZDM3OSIsIjA3YWI5NTg1LTkxMWYtNGJkMi04NWU5LWU1NGIwMDI1YTc3MCIsImQzM2ZjNzg2LTk3ZjYtNDIyZC04MWZjLWI3NzZiZDU1YzFmOCIsIjI4ZTRmNjg5LTMzNTAtNDdhOC04ZmRiLTdiZDMyOTFkYzY3MCIsIjRmNDhiNjhhLTZlY2UtNDM4MS04MWNjLWY3NTVjN2FlOWU2NiIsImFhOWMwYjhjLTNmYjEtNDBkZC1hYjhlLTU4NjM1ZGVlZjc5ZSIsIjNhNTIwYzkxLTA2ZjctNDJhMi1hM2NmLWFjODQyNGRlYWNhNiIsImVmMWNjMDkzLThlNzgtNGI0ZC1hMmFlLTMyNzhjM2I2ZGVkZCIsIjMzOWQ2ZTk0LTNhYTctNDkwYi05MDkzLTNhNDdkODQzNTVjNCIsIjFhNTI3NTk4LWE2MmItNGQ1MC1hMzRkLTIxNDZiNTU0MWFkYiIsIjIwYjVkYTljLWFjNTItNDMyNS1iYmI2LWIzNmIxZGZkMDc2MSIsIjZiMWFlOTllLTU0NmUtNGU2NS04NmMxLTQxNTgyODc0OGVkNSIsIjVlMWJkYjlmLTc3ODgtNDdlZi1hMGVmLTUyN2NjODkyNTFlNSIsIjZiOThjOWExLTk3ZmMtNDA0OC04M2YyLWQ4MTNhYzYxOTMyZCIsImE0MzZiY2EyLWQ1NDMtNDUyMC05MTc2LTU4NDAwMThiNGNkNyIsIjgwODY2M2E2LWU4N2ItNDY3OC05NDliLWQ1ZDM3MmJjNWZmOCIsIjk4OGUyYWFlLTNkY2EtNDA0YS04ZTI2LTljYWEyZjBkOTNhMSIsIjFkM2JhN2FmLWIxNTktNDY0ZC04ODgyLWY4YmEwNmNlMWViMiIsIjUzYmRmNWIxLTZjOTItNGE0Ni05MjMwLTdiNjNjMTg2OWNlZSIsIjRhYTRiOGIyLTQxZmItNGNhMS05YzA4LWYyOGM0NDdkNDJjZCIsImY5Zjk2YmI3LTQzMDktNGEyOS05Mzg0LWFkMDA3ZmNiZTUxYSIsIjM0YzBmY2I5LWU5Y2YtNGZjNy1iMGEzLTc5ZmUzNWVmODNiNiIsIjIwODU3ZGMwLTAyNTAtNDVhNS1iMDc2LTY3OTIzZmU1ODM0YiIsIjU0NDg0M2MyLWZlZjctNDU4OS1iY2NlLWNiODdlYTgyNWY0YiIsIjdlOGE2Y2M2LWNlMmItNDY4Zi05MmYwLTJkOTQ4ZTFiNjgwMyIsIjI0NTdhYmM3LWI4ZTQtNDA0Mi05ZTk3LTM3MzJlOTU2NGY5OCIsImE0YzA5ZmM5LTY0OTQtNGQ3Yi1hZWY2LTVhMTlkODFhNzkyNSIsImQ0MWNlOWNhLWI5YWYtNDk3OS1hMzBkLTQ2OWY1ZDVmYzU5YiIsIjIxOTNiOWNiLWQ5ODctNDE2ZC05OWI2LTEwNjc2NWU5YTM0MCIsIjg0N2M3ZGNlLTViMzAtNGNkMS1hNTJmLWIzZGM3MDQ0OTY2NyIsImM2YjExMmQyLWEzMzgtNGIzNS05MjFlLTk3MDIyYmFlMGY3MCIsImUxMWRlNmQzLWY0ZmYtNDU0MC04YzMzLTNjMzg3N2FhYjE5NiIsIjhmMGUwNWQ1LTM4MTktNGVjMi1iMjgxLTRhZmM1NzQ4YWM2NCIsImQyYmQ5NGQ1LTcyMzktNDMxZS1hMWQ2LWY3ZDExY2U5NDVjMiIsImM0OWE3M2Q3LTlkYzktNDhiNy1hNjE1LTkyNzhlMzg3MmQ2ZCIsImM1ZjUxMGQ5LTJlZDQtNGEzMC1iMGFkLTZmMjA0NDc4NDc3MyIsImQ0MWYyNmRlLTY1MjEtNGY1Ny1hMDJmLWQ5NjhkNjBiNmE5YSIsImRjZGNjMmRlLWQ3ZmItNDI5Ny1iYTNhLTBlYTg2NzdhNzdjOSIsImVmYWI1YWRmLWY3YWUtNDYyZi05YzUwLWU3NDViM2Y2ODUyMyIsIjE1ZTI2NWUxLTU0ODktNDUyMC05ZTgyLTQxODVmMGQwYzQyNyIsIjA4NjMxNmUzLTkxNjEtNDg5My1iYzVlLThkMDc5OWM4NWZiZiIsIjZmYWYzYmU0LTMzYWQtNDQ1Yi04ODJkLTkxMzA4Y2M5NWNhMSIsIjAwODRkYmVhLTY2NGEtNDNkMi04ZTdjLTJmYzFkMDM0NjFmNyIsImE3NTg4NmVlLTljMWUtNDVkMi05MzI3LWFjNWI3YTg1YmZiOCIsImMyM2M5OGYzLTQzYTEtNDAwMS05MjE0LWNlMzgwYjUyZTFmYiIsIjU2MWY0ZWZjLTljNDgtNDU4MS1iNWI5LWMwNDEzYmU3MjcyOSIsIjQ4YTE2ZWZlLTMyYTQtNGM5YS04OTcwLTY3NDNiNzlmZWM2OSIsImE5OTgwNWZmLTA5OGQtNDg0Yi04ODAwLWExMDMwZDc3ZDA5MCIsImFkMGEyNGZmLTg3MDAtNDI3ZS05NmY3LTVjMjgzMzRjNmFiMiJdLCJpcGFkZHIiOiIxMDMuMjI3LjQyLjE3IiwibmFtZSI6IlJhbWFsLCBOaWtrbyIsIm9pZCI6IjFlZTA0ZTFjLTU2NjItNDA3Yy1hNTg0LThlOTZkMzRlMGVkYyIsIm9ucHJlbV9zaWQiOiJTLTEtNS0yMS0zNzUxNjE1Mjk0LTUwNzIwNzczOS0xMjYxMTk5NjIxLTc2NjI4MzkiLCJwdWlkIjoiMTAwMzIwMDE0RjI5OEE1MyIsInJoIjoiMC5BVnNBTXEzbFpBVEwzMFNJbHI3VjEza2tLWkFpTVgzSUtEeEhvTzJPVTNTYmJXMWJBQ00uIiwic2NwIjoidXNlcl9pbXBlcnNvbmF0aW9uIiwic3ViIjoiWnVvVU9hV0dKWDRYTk9PS3Y1REdsVy1JbFFNWnB3cFZjZkNteUhNcDFfTSIsInRpZCI6IjY0ZTVhZDMyLWNiMDQtNDRkZi04ODk2LWJlZDVkNzc5MjQyOSIsInVuaXF1ZV9uYW1lIjoiTmlra28uUmFtYWxAYXN1cmlvbi5jb20iLCJ1cG4iOiJOaWtrby5SYW1hbEBhc3VyaW9uLmNvbSIsInV0aSI6IldXUldYWFdSNWtLUWRmNDVWc2FpQUEiLCJ2ZXIiOiIxLjAiLCJ3aWRzIjpbImI3OWZiZjRkLTNlZjktNDY4OS04MTQzLTc2YjE5NGU4NTUwOSJdfQ.OOimpBrpfr-_4y0Y3179QGiao4oYlfXad1uWvg2xrlfBjCnfoaMVR88sqJhnxiGA7dTFPMQNUPiQTgALll3vZtVTYNcpTPcvJsPBCjWtOj4nN5jhCUlPyzd5xFwGSUmcjpMb20bAVB95beTMS53HE5UYH3vw5WkvJaIF75XaApUnE9WcDg-mmaV1EboKQM90Snhtc6aRtk-GkC5Xhadq2qyruRB3WH7TfT6AqqXelpm5P8I28C06IAljwSDhVyJG6buy7ZdrT5BDJorMZTT3jJT4OiG58sZQI_pGzFvHhBxFBxHdmiEVTBTve0Jum9xRye6Kw6l1MpG1svt1IaNG8Q'
    # Process the conversation history using OpenAI  
    #output = openai.ChatCompletion.create(
    #    model="gpt-4",
    #    temperature=0.7,
    #    presence_penalty=0,
    #    frequency_penalty=0,
    #    max_tokens=4000,
    #    messages=[
    #        {"role": "system", "content": f"{impersonated_role}. Conversation history: {conversation_history}"},
    #        {"role": "user", "content": f"{user_message}"},
    #    ]
    #) 
    url = 'https://ai27.openai.azure.com/openai/deployments/gpt-4/chat/completions?api-version=2023-07-01-preview'
    payload = json.dumps({
    "messages": [
        {"role": "system", "content": f"{impersonated_role}. Conversation history: {conversation_history}"},
        {"role": "user", "content": f"{user_message}"},
    ]
    })
    headers = {
    'Content-Type': 'application/json',
    'Authorization': f"{auth_bearer}"
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    
    # Parse the JSON response
    output = json.loads(response.text)
    
    ## Get the assistant's response and add it to the conversation history  
    assistant_message = output['choices'][0]['message']['content']  
    #conversation_history.append({"role": "assistant", "content": assistant_message})

    if '```python' in assistant_message: 
        res, d = extract_and_execute_python_code2(assistant_message, exec_globals)
        res=res[0]
        conversation_history.append({"role": "assistant", "content": res})
        return jsonify({'response': res, 'd_type':d[0]})
    else:
        dd = 'str'
        conversation_history.append({"role": "assistant", "content": assistant_message})
        return jsonify({'response': assistant_message, 'd_type':dd})
    

if __name__ == '__main__':
    app.run(debug=True)
