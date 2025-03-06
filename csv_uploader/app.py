import io
from flask import Flask, request, render_template, jsonify, send_file # type: ignore
import pandas as pd # type: ignore
import os
import glob
import math
from flask_sqlalchemy import SQLAlchemy # type: ignore

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploaded_files'

# Configure Database
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(BASE_DIR, "attendance.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class AttendanceFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    semester_type = db.Column(db.String(10), nullable=False)
    csv_file = db.Column(db.LargeBinary, nullable=False)

    __table_args__ = (db.UniqueConstraint('year', 'semester_type', name='unique_semester'),)

def clear_upload_folder():
    files = glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], '*'))
    for f in files:
        os.remove(f)

# Function to determine semester type
def get_semester_type(month):
    if month in [9, 10, 11, 12, 1]:
        return "Odd"
    elif month in [2, 3, 4, 5, 6]:
        return "Even"
    elif month in [7, 8]:
        return "Compact"
    return None

# Create the upload folder if it does not exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Clear the upload folder when the app starts
clear_upload_folder()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'})

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No file selected'})

    if file and file.filename.endswith('.csv'):
        try:
            parts = file.filename.split(' ')
            date_part = parts[-1].replace('.csv', '').lstrip('-') # Get last part and remove .csv
            day, month, year = map(int, date_part.split('-')) # Get date components

            # January is part of the previous year's even odd semester
            if month < 9:
                year -= 1
                
        except ValueError:
            return jsonify({'error': 'Invalid filename format.'})
        
        semester_type = get_semester_type(month)
        if not semester_type:
            return jsonify({'error': 'Invalid semester received from file name.'})

        # Load the CSV into a pandas DataFrame
        df = pd.read_csv(file, delimiter=";", encoding="Windows-1252")

        # Map values in "PRESENT" column: Y -> 1, N -> 0
        if 'PRESENT' in df.columns:
            df['PRESENT'] = df['PRESENT'].map({'Y': 1, 'N': 0})

        # Exclude rows where 'COURSE NAME' is one of the specified courses
        excluded_courses = ['Excellence Program I', 'English Plus Stage One', 'English Plus Stage Two', 'Academic Advisory']
        df = df[~df['COURSE NAME'].isin(excluded_courses)]

        # Exclude rows where 'MAJOR' is 'Non Degree Program'
        df = df[df['MAJOR'] != 'Non Degree Program']

        # Consider both "Fashion Design" and "Fashion Management" as just 'Fashion'
        df['MAJOR'].replace('Fashion Design', 'Fashion', inplace=True)
        df['MAJOR'].replace('Fashion Management', 'Fashion', inplace=True)

        # Remove old files
        old_files = glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], "main_data_*.csv"))
        for old_file in old_files:
            os.remove(old_file)

        # Save the uploaded CSV file locally for this instance
        file_name = f"main_data_{semester_type}_{year}.csv"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_name)
        file.save(file_path)
        df.to_csv(file_path, index=False, sep=";")

        # Convert DataFrame back to CSV
        csv_data = df.to_csv(index=False, sep=";").encode()

        # Check if an entry for this specific semester already exists
        existing_entry = AttendanceFile.query.filter_by(year=year, semester_type=semester_type).first()

        if existing_entry:
            existing_entry.csv_file = csv_data  # Replace existing file
        else:
            new_entry = AttendanceFile(year=year, semester_type=semester_type, csv_file=csv_data) # New entry
            db.session.add(new_entry)
        
        db.session.commit()

        # Indicate success
        return jsonify({'fileSemesterType': semester_type, 'fileYear': year,'success': 'File uploaded and stored successfully'})

    else:
        return jsonify({'error': 'Invalid file format'})

@app.route('/retrieve', methods=['POST'])
def retrieve_file():
    data = request.get_json()
    year = data.get('year')
    semester_type = data.get('semester_type')

    if not year or not semester_type:
        return jsonify({'error': 'Year and semester type needed.'})

    # Try querying the database
    entry = AttendanceFile.query.filter_by(year=year, semester_type=semester_type).first()
    
    if not entry:
        return jsonify({'error': 'No data found for the selected semester and year.'})

    # Convert the stored BLOB back to a CSV file, save it in local storage
    file_name = f"main_data_{entry.semester_type}_{entry.year}.csv"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_name)

    old_files = glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], "main_data_*.csv"))
    for old_file in old_files:
        os.remove(old_file)

    with open(file_path, 'wb') as f:
        f.write(entry.csv_file)  # Write kthe binary data to a file

    return jsonify({'fileSemesterType': entry.semester_type, 'fileYear': entry.year, 'success': 'File retrieved and saved locally.'})


@app.route('/get_dataframe', methods=['POST'])
def get_dataframe():
    data = request.get_json()
    filter_exl = data.get('filterEXL')

    files = glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], "main_data_*.csv"))

    if len(files) == 0:
        return jsonify({'error': 'No data found'})
    elif len(files) > 1:
        return jsonify({'error': 'Multiple files found in folder'})
    else:
        df = pd.read_csv(files[0], delimiter=";", encoding="Windows-1252")

        # Filter to show only the desired columns
        filtered_columns = ["BINUSIAN ID", "NIM", "NAME", "MAJOR", "COMPONENT", "COURSE NAME", "SESSION ID NUM", "PRESENT"]

        if set(filtered_columns).issubset(df.columns):
            # Filter the DataFrame to only include the specific columns
            df_filtered = df[filtered_columns]

            if filter_exl:
                df_filtered = df_filtered[df_filtered['COMPONENT'] != 'EXL']

            # Convert filtered DataFrame to HTML for display
            df_html = df_filtered.to_html(classes='table table-striped', index=False)

            return jsonify({'data': df_html})
        else:
            return jsonify({'error': 'Required columns are missing from the CSV file'})


@app.route('/aggregate_by_nim', methods=['POST'])
def aggregate_by_nim():
    files = glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], "main_data_*.csv"))

    data = request.get_json()
    filter_exl = data.get('filterEXL')

    if len(files) == 0:
        return jsonify({'error': 'No data found'})
    elif len(files) > 1:
        return jsonify({'error': 'Multiple files found in folder'})
    else:
        try:
            df = pd.read_csv(files[0], delimiter=";", encoding="Windows-1252")

            if filter_exl:
                df = df[df['COMPONENT'] != 'EXL']

            # Map the SKS to the total possible sessions till the end of the semester
            def calculate_total_semester_sessions(sks):
                # Convert SKS to expected semester sessions: floor(SKS/2) * 13
                return (sks // 2) * 13

            # Assuming SKS is already present in the data, you may need to adjust based on your actual data
            if 'SKS' in df.columns:
                df['TOTAL_SEMESTER_SESSIONS'] = df['SKS'].apply(calculate_total_semester_sessions)
                
            # Group by NIM, NAME, MAJOR and COURSE first to calculate total sessions per semester per course 
            df_course_grouped = df.groupby(['NIM', 'NAME', 'MAJOR', 'COURSE CODE', 'COMPONENT']).agg(
                TOTAL_PRESENT=('PRESENT', 'sum'),
                TOTAL_SESSIONS=('SESSION ID NUM', 'count'),  
                TOTAL_SEMESTER_SESSIONS=('TOTAL_SEMESTER_SESSIONS', 'first') 
            ).reset_index()

            # Group by NIM, NAME, and MAJOR to calculate total sessions and total present
            grouped = df_course_grouped.groupby(['NIM', 'NAME', 'MAJOR']).agg(
                TOTAL_PRESENT=('TOTAL_PRESENT', 'sum'),
                TOTAL_SESSIONS=('TOTAL_SESSIONS', 'sum'),  # Current sessions
                TOTAL_SEMESTER_SESSIONS=('TOTAL_SEMESTER_SESSIONS', 'sum')  # Expected total sessions till semester end
            ).reset_index()

            # Filter out students with 0 total sessions
            grouped = grouped[grouped['TOTAL_SESSIONS'] > 0]

            # Calculate percentage of attendance based on current sessions
            grouped['PERCENTAGE_ATTENDANCE'] = (grouped['TOTAL_PRESENT'] / grouped['TOTAL_SESSIONS']) * 100

            # Calculate percentage attendance so far for the semester
            grouped['PERCENTAGE_ATTENDANCE_SEMESTER'] = (
                grouped['TOTAL_PRESENT'] /
                grouped['TOTAL_SEMESTER_SESSIONS']
            ) * 100

            # Calculated projected percentage attendance (assume all sessions that have yet to happen to be present)
            grouped['PROJECTED_ATTENDANCE_SEMESTER'] = (
                (grouped['TOTAL_SEMESTER_SESSIONS'] - 
                grouped['TOTAL_SESSIONS'] + 
                grouped['TOTAL_PRESENT'])/ 
                grouped['TOTAL_SEMESTER_SESSIONS']
            ) * 100

            # Format the percentage to two decimal places and add % sign
            grouped['PERCENTAGE_ATTENDANCE'] = grouped['PERCENTAGE_ATTENDANCE'].apply(lambda x: math.ceil(x))
            grouped['PERCENTAGE_ATTENDANCE_SEMESTER'] = grouped['PERCENTAGE_ATTENDANCE_SEMESTER'].apply(lambda x: math.ceil(x))
            grouped['PROJECTED_ATTENDANCE_SEMESTER'] = grouped['PROJECTED_ATTENDANCE_SEMESTER'].apply(lambda x: math.ceil(x))

            # Exclude rows where PERCENTAGE_ATTENDANCE_SEMESTER is 100%
            grouped = grouped[grouped['PERCENTAGE_ATTENDANCE_SEMESTER'] != '100.00%']

            # Save the aggregated DataFrame
            aggregated_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'nim_aggregate.csv')
            grouped.to_csv(aggregated_file_path, index=False, sep=";")

            return jsonify({'success': 'Aggregation completed'})
        except Exception as e:
            return jsonify({'error': str(e)})


@app.route('/get_nim_aggregate', methods=['GET'])
def get_nim_aggregate():
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'nim_aggregate.csv')
    if os.path.exists(file_path):
        df = pd.read_csv(file_path, delimiter=";", encoding="Windows-1252")
        df_html = df.to_html(classes='table table-striped', index=False)
        return jsonify({'data': df_html})
    else:
        return jsonify({'error': 'No NIM Aggregate DataFrame available'})

@app.route('/aggregate_by_nim_course', methods=['POST'])
def aggregate_by_nim_course():
    files = glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], "main_data_*.csv"))

    if len(files) == 0:
        return jsonify({'error': 'No data found'})
    elif len(files) > 1:
        return jsonify({'error': 'Multiple files found in folder'})
    else:
        try:
            df = pd.read_csv(files[0], delimiter=";", encoding="Windows-1252")
            
            # Calculate total sessions for COURSE NAME
            if 'SKS' in df.columns:
                df['TOTAL_SESSIONS_SEMESTER'] = (df['SKS'] // 2) * 13

            # Group by 'NIM' and 'COURSE ID' and calculate the count of 'PRESENT'
            grouped = df.groupby(['NIM', 'COURSE CODE', 'COMPONENT']).agg({
                'PRESENT': 'sum',
                'SESSION ID NUM': 'count'
            }).reset_index()

            # Rename columns for clarity
            grouped.columns = ['NIM', 'COURSE CODE', 'COMPONENT', 'TOTAL_PRESENT', 'TOTAL_SESSIONS']

            # Merge with total sessions to get total sessions per course
            grouped = grouped.merge(df[['COURSE CODE', 'TOTAL_SESSIONS_SEMESTER']].drop_duplicates(), on='COURSE CODE', how='left')

            # Merge with original dataframe to get 'BINUSIAN ID' and 'NAME'
            grouped = grouped.merge(
                df[['NIM', 'COURSE CODE', 'BINUSIAN ID', 'NAME', 'COURSE NAME']].drop_duplicates(), 
                on=['NIM', 'COURSE CODE'], 
                how='left'
            )


            grouped['PERCENTAGE_ATTENDANCE_SEMESTER'] = (grouped['TOTAL_PRESENT'] / grouped['TOTAL_SESSIONS_SEMESTER']) * 100
            grouped['PERCENTAGE_ATTENDANCE'] = (grouped['TOTAL_PRESENT'] / grouped['TOTAL_SESSIONS']) * 100
             # Calculated projected percentage attendance (assume all sessions that have yet to happen to be present)
            grouped['PROJECTED_ATTENDANCE_SEMESTER'] = (
                (grouped['TOTAL_SESSIONS_SEMESTER'] - 
                grouped['TOTAL_SESSIONS'] + 
                grouped['TOTAL_PRESENT'])/ 
                grouped['TOTAL_SESSIONS_SEMESTER']
            ) * 100
            
            grouped['PERCENTAGE_ATTENDANCE'] = grouped['PERCENTAGE_ATTENDANCE'].apply(lambda x: math.ceil(x))
            grouped['PERCENTAGE_ATTENDANCE_SEMESTER'] = grouped['PERCENTAGE_ATTENDANCE_SEMESTER'].apply(lambda x: math.ceil(x))
            grouped['PROJECTED_ATTENDANCE_SEMESTER'] = grouped['PROJECTED_ATTENDANCE_SEMESTER'].apply(lambda x: math.ceil(x))

            # Reorder columns for clarity
            grouped = grouped[['NIM', 'BINUSIAN ID', 'NAME', 'COURSE CODE', 'COURSE NAME', 'COMPONENT', 'TOTAL_PRESENT', 'TOTAL_SESSIONS', 'TOTAL_SESSIONS_SEMESTER', 'PERCENTAGE_ATTENDANCE', 'PERCENTAGE_ATTENDANCE_SEMESTER', 'PROJECTED_ATTENDANCE_SEMESTER']]

            # Save the aggregated DataFrame
            aggregated_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'nim_course_aggregate.csv')
            grouped.to_csv(aggregated_file_path, index=False, sep=";")

            # Debugging output
            print("Aggregated DataFrame:")
            print(grouped)

            return jsonify({'success': 'Aggregation completed'})
        except Exception as e:
            return jsonify({'error': str(e)})

@app.route('/get_nim_course_aggregate', methods=['POST'])
def get_nim_course_aggregate():
    data = request.get_json()
    filter_exl = data.get('filterEXL')
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'nim_course_aggregate.csv')
    if os.path.exists(file_path):
        df = pd.read_csv(file_path, delimiter=";", encoding="Windows-1252")
        if filter_exl:
            df = df[df['COMPONENT'] != 'EXL']
        df_html = df.to_html(classes='table table-striped', index=False)
        return jsonify({'data': df_html})
    else:
        return jsonify({'error': 'No NIM Course Aggregate DataFrame available'})

@app.route('/export_to_excel/<string:filename>')
def export_to_excel(filename):
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(file_path):
        df = pd.read_csv(file_path, delimiter=";", encoding="Windows-1252")
        df.to_excel(file_path.replace('.csv', '.xlsx'), index=False)
        return send_file(file_path.replace('.csv', '.xlsx'), as_attachment=True, download_name=f"{filename}.xlsx")
    else:
        return jsonify({'error': 'File not found'})

@app.route('/filter_major', methods=['GET'])
def filter_major():
    major_search_term = request.args.get('major')

    if not major_search_term:
        return jsonify({'error': 'No search term provided'}), 400

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'uploaded_data.csv')

    if os.path.exists(file_path):
        df = pd.read_csv(file_path, delimiter=";", encoding="Windows-1252")

        # Filter the DataFrame by "MAJOR" column, case-insensitive search
        filtered_df = df[df['MAJOR'].str.contains(major_search_term, case=False, na=False)]

        # Convert the filtered DataFrame to HTML
        df_html = filtered_df.to_html(classes='table table-striped', index=False)
        return jsonify({'data': df_html})
    else:
        return jsonify({'error': 'No DataFrame available'})

@app.route('/get_pie_chart_data', methods=['POST'])
def get_pie_chart_data():
    data = request.get_json()
    year = data.get('year')
    semester_type = data.get('semester_type')
    value = data.get('value')
    major = data.get('major')
    threshold = data.get('threshold')
    divisor = data.get('divisor')

    # Query database for data of selected seester
    entry = AttendanceFile.query.filter_by(year=year, semester_type=semester_type).first()
    if not entry:
        return jsonify({'error': 'No data found for this semester.'})

    # Load CSV
    df = pd.read_csv(io.BytesIO(entry.csv_file), delimiter=";", encoding="Windows-1252")

    # Only show selected major
    df = df[df['MAJOR'] == major]
    
    if divisor == 'Present':
        # Calculate attendance percentage
        attendance = df.groupby('NIM')['PRESENT'].sum() / df.groupby('NIM')['SESSION ID NUM'].count() * 100
    elif divisor == 'Projected':
        # Get total semester sessions
        df['TOTAL_SEMESTER_SESSIONS'] = (df['SKS'] // 2) * 13

        # Get semester sessions per course
        df_grouped = df.groupby(['NIM', 'COURSE CODE', 'COMPONENT']).agg(
            TOTAL_PRESENT=('PRESENT', 'sum'),
            TOTAL_SESSIONS=('SESSION ID NUM', 'count'),  
            TOTAL_SEMESTER_SESSIONS=('TOTAL_SEMESTER_SESSIONS', 'first') 
        ).reset_index()

        # Now per student
        grouped = df_grouped.groupby(['NIM']).agg(
            TOTAL_PRESENT=('TOTAL_PRESENT', 'sum'),
            TOTAL_SESSIONS=('TOTAL_SESSIONS', 'sum'),  
            TOTAL_SEMESTER_SESSIONS=('TOTAL_SEMESTER_SESSIONS', 'sum') 
        ).reset_index()
        
        attendance = ((grouped['TOTAL_SEMESTER_SESSIONS'] - grouped['TOTAL_SESSIONS'] + grouped['TOTAL_PRESENT']) / grouped['TOTAL_SEMESTER_SESSIONS']) * 100
    else:
        return jsonify({'error': 'Invalid divisor for attendance calculation'})

    # Count students below and above the threshold
    below_threshold = (attendance < threshold).sum()
    above_threshold = (attendance >= threshold).sum()
    total = int(below_threshold) + int(above_threshold)

    if value == 'Number':
        return jsonify({'below_50': int(below_threshold), 'above_50': int(above_threshold)})
    elif value == 'Percentage':
        return jsonify({'below_50': round((int(below_threshold) / total * 100), 2), 'above_50': round((int(above_threshold) / total * 100), 2)})

@app.route('/get_bar_chart_major_data', methods=['POST'])
def get_bar_chart_major_data():
    data = request.get_json()
    year = data.get('year')
    semester_type = data.get('semester_type')
    value = data.get('value')
    majors = data.get('majors')
    threshold = data.get('threshold')
    divisor = data.get('divisor')

    # Query database for data of selected seester
    entry = AttendanceFile.query.filter_by(year=year, semester_type=semester_type).first()
    if not entry:
        return jsonify({'error': 'No data found for this semester.'})

    # Load CSV
    df = pd.read_csv(io.BytesIO(entry.csv_file), delimiter=";", encoding="Windows-1252")

    # Only show selected majors
    df = df[df['MAJOR'].isin(majors)]

    if divisor == 'Present':
        # Calculate attendance percentage
        attendance = df.groupby('NIM')['PRESENT'].sum() / df.groupby('NIM')['SESSION ID NUM'].count() * 100
    elif divisor == 'Projected':
        # Get total semester sessions
        df['TOTAL_SEMESTER_SESSIONS'] = (df['SKS'] // 2) * 13

        # Get semester sessions per course
        df_grouped = df.groupby(['NIM', 'COURSE CODE', 'COMPONENT']).agg(
            TOTAL_PRESENT=('PRESENT', 'sum'),
            TOTAL_SESSIONS=('SESSION ID NUM', 'count'),  
            TOTAL_SEMESTER_SESSIONS=('TOTAL_SEMESTER_SESSIONS', 'first') 
        ).reset_index()

        # Now per student
        grouped = df_grouped.groupby(['NIM']).agg(
            TOTAL_PRESENT=('TOTAL_PRESENT', 'sum'),
            TOTAL_SESSIONS=('TOTAL_SESSIONS', 'sum'),  
            TOTAL_SEMESTER_SESSIONS=('TOTAL_SEMESTER_SESSIONS', 'sum') 
        )
        
        attendance = ((grouped['TOTAL_SEMESTER_SESSIONS'] - grouped['TOTAL_SESSIONS'] + grouped['TOTAL_PRESENT']) / grouped['TOTAL_SEMESTER_SESSIONS']) * 100

    # For all students and their major
    df_students = df[['NIM', 'MAJOR']].drop_duplicates()  
    df_students['Below_threshold'] = df_students['NIM'].map(attendance < threshold)

    if value == 'Number':
        # Count num of students under 50% per major
        results = df_students.groupby('MAJOR')['Below_threshold'].sum().reset_index()
    elif value == 'Percentage':
        # Count total students per major and number of students under 50%, then divide
        students_in_major = df_students.groupby('MAJOR')['NIM'].count()
        below_threshold_in_major = df_students.groupby('MAJOR')['Below_threshold'].sum()

        results = (round((below_threshold_in_major / students_in_major * 100), 2)).reset_index()
    
    results.columns = ['Major', 'Below_threshold']

    # Convert to dict
    result_dict = dict(zip(results['Major'], results['Below_threshold'])) 

    return jsonify(result_dict)

# Function to sort semesters in chronological order
def semester_sort(semester):
    semester_type, year = semester.split()
    year = int(year)

    # Assign order to semester types
    semester_order = {
        "Even": 2, # Feb - June
        "Compact": 3, # July - August
        "Odd": 1     # Sept - Jan
    }

    # Sort by year first, then semester type
    return (year, semester_order[semester_type])

@app.route('/get_bar_chart_student_data', methods=['POST'])
def get_bar_chart_student_data():
    data = request.get_json()
    nim = data.get('nim')
    threshold = data.get('threshold')
    divisor = data.get('divisor')

    # Query all tables in the database, one for each semester
    all_entries = AttendanceFile.query.all()

    # Dictionary to store results, and variable to store student name
    results = {}
    not_enrolled = []
    student_name = None

    # Loop through all tables
    for entry in all_entries:
        # Construct the current entry's semester
        current_semester = f"{entry.semester_type} {entry.year}"

        # Load CSV
        df = pd.read_csv(io.BytesIO(entry.csv_file), delimiter=";", encoding="Windows-1252")

        # Only show selected student
        student_rows = df[df['NIM'] == int(nim)]

        print(student_rows)

        # If the student isn't in the semester, move on to the next one
        if student_rows.empty:
            results[current_semester] = 0
            not_enrolled.append(current_semester)
            continue  
        
        # Get student's name if it doesn't exist
        if student_name is None:
            student_name = student_rows.iloc[0]['NAME']

        if divisor == 'Present':
        # Calculate attendance percentage
            attendance = student_rows.groupby(['COURSE CODE', 'COMPONENT'])['PRESENT'].sum() / student_rows.groupby(['COURSE CODE', 'COMPONENT'])['SESSION ID NUM'].count() * 100
        elif divisor == 'Projected':
            # Get total semester sessions
            student_rows['TOTAL_SEMESTER_SESSIONS'] = (student_rows['SKS'] // 2) * 13

            # Get semester sessions per course
            grouped = student_rows.groupby(['COURSE CODE', 'COMPONENT']).agg(
                TOTAL_PRESENT=('PRESENT', 'sum'),
                TOTAL_SESSIONS=('SESSION ID NUM', 'count'),  
                TOTAL_SEMESTER_SESSIONS=('TOTAL_SEMESTER_SESSIONS', 'first') 
            ).reset_index()
        
            attendance = ((grouped['TOTAL_SEMESTER_SESSIONS'] - grouped['TOTAL_SESSIONS'] + grouped['TOTAL_PRESENT']) / grouped['TOTAL_SEMESTER_SESSIONS']) * 100

        below_threshold = (attendance < threshold).sum()

        results[current_semester] = int(below_threshold)
    
    if not bool(results):
        return jsonify({'error': 'Student not found in any semester.'})
    
    # Sorting the dictionary so the semesters are in chronological order
    results_sorted = {semester: results[semester] for semester in sorted(results.keys(), key=semester_sort)}

    if len(results_sorted) < 21:
        return jsonify({"name": student_name, "not_enrolled": not_enrolled, "data": [{"semester": s, "count": c} for s, c in results_sorted.items()]})
    else:
        return jsonify({"name": student_name, "not_enrolled": not_enrolled, "data": [{"semester": s, "count": c} for s, c in list(results_sorted.items())[-21:]]})


@app.route('/get_bar_chart_course_data', methods=['POST'])
def get_bar_chart_course_data():
    data = request.get_json()
    course = data.get('course')
    component = data.get('component')
    value = data.get('value')
    semester_count = data.get('semester_count')
    threshold = data.get('threshold')
    divisor = data.get('divisor')

    # Query all tables in the database, one for each semester
    all_entries = AttendanceFile.query.all()

    # Dictionary to store results, and variable to store student name
    results = {}
    course_name = None

    # Loop through all tables
    for entry in all_entries:
        # Construct the current entry's semester
        current_semester = f"{entry.semester_type} {entry.year}"

        # Load CSV
        df = pd.read_csv(io.BytesIO(entry.csv_file), delimiter=";", encoding="Windows-1252")

        # Only show selected course
        course_rows = df[df['COURSE CODE'] == course]

        # Show the correct component
        course_rows = course_rows[course_rows['COMPONENT']== component]

        # If the course isn't in the semester, move on to the next one
        if course_rows.empty:
            continue  
        
        # Get coursename if it doesn't exist
        if course_name is None:
            course_name = course_rows.iloc[0]['COURSE NAME']

        # Calculate attendance percentage per course
        attendance = course_rows.groupby('NIM')['PRESENT'].sum() / course_rows.groupby('NIM')['SESSION ID NUM'].count() * 100

        if divisor == 'Present':
            # Calculate attendance percentage
            attendance =course_rows.groupby('NIM')['PRESENT'].sum() / course_rows.groupby('NIM')['SESSION ID NUM'].count() * 100
        elif divisor == 'Projected':
            # Get total semester sessions
            course_rows['TOTAL_SEMESTER_SESSIONS'] = (course_rows['SKS'] // 2) * 13

            # Get semester sessions
            grouped = course_rows.groupby(['NIM']).agg(
                TOTAL_PRESENT=('PRESENT', 'sum'),
                TOTAL_SESSIONS=('SESSION ID NUM', 'count'),  
                TOTAL_SEMESTER_SESSIONS=('TOTAL_SEMESTER_SESSIONS', 'first') 
            ).reset_index()
        
            attendance = ((grouped['TOTAL_SEMESTER_SESSIONS'] - grouped['TOTAL_SESSIONS'] + grouped['TOTAL_PRESENT']) / grouped['TOTAL_SEMESTER_SESSIONS']) * 100

        below_threshold = (attendance < threshold).sum()

        if value == 'Percentage':
            num_of_students = course_rows['NIM'].nunique()
            results[current_semester] = round((int(below_threshold) / num_of_students * 100), 2)
        
        else:
            results[current_semester] = int(below_threshold)
    
    if not bool(results):
        return jsonify({'error': 'Course not found in any semester.'})
    
    # Sorting the dictionary so the semesters are in chronological order
    results_sorted = {semester: results[semester] for semester in sorted(results.keys(), key=semester_sort)}

    print(results_sorted.items())

    if len(results_sorted) < int(semester_count):
        return jsonify({"name": course_name, "data": [{"semester": s, "count": c} for s, c in results_sorted.items()]})
    else:
        return jsonify({"name": course_name, "data": [{"semester": s, "count": c} for s, c in list(results_sorted.items())[-int(semester_count):]]})

@app.route('/get_bar_chart_student_course_data', methods=['POST'])
def get_bar_chart_student_course_data():
    data = request.get_json()
    nim = data.get('nim')
    course = data.get('course')
    component = data.get('component')
    value = data.get('value')

    # Query all tables in the database, one for each semester
    all_entries = AttendanceFile.query.all()

    # Dictionary to store results, and variable to store student name
    results = {}
    course_name = None
    student_name = None

    # Loop through all tables
    for entry in all_entries:
        # Construct the current entry's semester
        current_semester = f"{entry.semester_type} {entry.year}"

        # Load CSV
        df = pd.read_csv(io.BytesIO(entry.csv_file), delimiter=";", encoding="Windows-1252")

        # Only show selected student
        student_rows = df[df['NIM'] == int(nim)]

        # Only show selected course
        course_rows = student_rows[student_rows['COURSE CODE'] == course]

        # Only show selected component
        course_rows = course_rows[course_rows['COMPONENT'] == component]

        # If the course isn't in the semester, move on to the next one
        if course_rows.empty:
            continue  
        
        # Get coursename if it doesn't exist
        if course_name is None or student_name is None:
            course_name = course_rows.iloc[0]['COURSE NAME']
            student_name = course_rows.iloc[0]['NAME']

        # Calculate attendance percentage per course
        attendance = course_rows['PRESENT'].sum()

        if value == 'Percentage':
            sessions = course_rows['SESSION ID NUM'].count()
            results[current_semester] = round((int(attendance) / int(sessions) * 100), 2)
        
        else:
            results[current_semester] = int(attendance)
    
    if not bool(results):
        return jsonify({'error': 'Course and student combination not found in any semester.'})
    
    # Sorting the dictionary so the semesters are in chronological order
    results_sorted = {semester: results[semester] for semester in sorted(results.keys(), key=semester_sort)}

    return jsonify({"course_name": course_name, "student_name": student_name, "data": [{"semester": s, "count": c} for s, c in results_sorted.items()]})



if __name__ == '__main__':
    app.run(debug=True)
