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

# Database structure
class AttendanceFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    semester_type = db.Column(db.String(10), nullable=False)
    csv_file = db.Column(db.LargeBinary, nullable=False)

    __table_args__ = (db.UniqueConstraint('year', 'semester_type', name='unique_semester'),)

# Clear all locally saved files from previous runs
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

# By default, load index.html
@app.route('/')
def index():
    return render_template('index.html')

# Load dashboard.html
@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/list_uploaded_files', methods=['GET'])
def list_uploaded_files():
    files = glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], '*'))
    filenames = [os.path.basename(f) for f in files]  
    return jsonify({'files': filenames})

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

        # Exclude rows where 'COURSE NAME' is one of the specified courses
        excluded_courses = ['Excellence Program I', 'English Plus Stage One', 'English Plus Stage Two', 'Academic Advisory']
        df = df[~df['COURSE NAME'].isin(excluded_courses)]

        # Exclude rows where 'MAJOR' is 'Non Degree Program'
        df = df[df['MAJOR'] != 'Non Degree Program']

        # Filter out students with 0 sessions so far
        df = df[df['SESSION DONE'] > 0]

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
        filtered_columns = ["NIM", "NAME", "MAJOR", "COURSE NAME", "COMPONENT", "SKS", "TOTAL SESSION", "SESSION DONE", "TOTAL ABSENCE", "MAX ABSENCE"]

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


@app.route('/get_nim_aggregate', methods=['GET'])
def get_nim_aggregate():
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'nim_aggregate.csv')
    if os.path.exists(file_path):
        df = pd.read_csv(file_path, delimiter=";", encoding="Windows-1252")
        df_html = df.to_html(classes='table table-striped', index=False)
        return jsonify({'data': df_html})
    else:
        return jsonify({'error': 'No NIM Aggregate DataFrame available'})

@app.route('/aggregate_tables', methods=['POST'])
def aggregate_tables():
    files = glob.glob(os.path.join(app.config['UPLOAD_FOLDER'], "main_data_*.csv"))

    if len(files) == 0:
        return jsonify({'error': 'No data found'})
    elif len(files) > 1:
        return jsonify({'error': 'Multiple files found in folder'})
    else:
        try:
            df = pd.read_csv(files[0], delimiter=";", encoding="Windows-1252")

            # Create a column for total present
            df['TOTAL PRESENT'] = df['SESSION DONE'] - df['TOTAL ABSENCE']

            # Calculate attendance so far and semester attendance
            df['PERCENTAGE_ATTENDANCE'] = (df['TOTAL PRESENT'] / df['SESSION DONE']) * 100
            df['PERCENTAGE_ATTENDANCE_SEMESTER'] = (df['TOTAL PRESENT'] / df['TOTAL SESSION']) * 100

             # Calculate projected percentage attendance (assume all sessions that have yet to happen to be present)
            df['PROJECTED_ATTENDANCE_SEMESTER'] = (
                1 - 
                (df['TOTAL ABSENCE'] / 
                df['TOTAL SESSION'])
            ) * 100
            
            # Format percentages
            df[['PERCENTAGE_ATTENDANCE', 'PERCENTAGE_ATTENDANCE_SEMESTER', 'PROJECTED_ATTENDANCE_SEMESTER']] = df[
                ['PERCENTAGE_ATTENDANCE', 'PERCENTAGE_ATTENDANCE_SEMESTER', 'PROJECTED_ATTENDANCE_SEMESTER']
            ].round(2)

            df['ELIGIBLE'] = df['TOTAL ABSENCE'] <= df['MAX ABSENCE']

            # Identify courses that have both LEC and LAB, where lec_lab_courses is a list of course codes with both LEC and LAB
            lec_lab_courses = df[df['COMPONENT'].isin(['LEC', 'LAB'])].groupby('COURSE CODE')['COMPONENT'].nunique()
            lec_lab_courses = lec_lab_courses[lec_lab_courses > 1].index.tolist()

            # Find students who failed either LEC or LAB for one of those courses
            failed_students = df[
                (df['COURSE CODE'].isin(lec_lab_courses)) &
                (df['COMPONENT'].isin(['LEC', 'LAB'])) & 
                (df['ELIGIBLE'] == False)
            ][['NIM', 'COURSE CODE']]

            # Find all rows where the eligible column needs to be set to false, based on the failed students
            failed_rows = (
                df.set_index(['NIM', 'COURSE CODE']).index.isin(
                    failed_students.set_index(['NIM', 'COURSE CODE']).index
                ) &
                (df['COMPONENT'].isin(['LEC', 'LAB']))  
            )

            # A new, temporary column to track indirect fails
            df['INDIRECT FAIL'] = False

            # Find all rows that will be indirect fails
            df.loc[failed_rows & (df['ELIGIBLE'] == True), 'INDIRECT FAIL'] = True  

            # Set all eligible to false for failed rows
            df.loc[failed_rows, 'ELIGIBLE'] = False

            # Drop columns
            df.drop(columns=['ACAD CAREER', 'STRM', 'BINUSIAN ID', 'TOTAL ABSENCE', 'MAX ABSENCE', 'SKS'], inplace=True)

            # Rename columns
            df.columns = ['NIM', 'NAME', 'MAJOR', 'COURSE CODE', 'COURSE NAME', 'CLASS', 'COMPONENT', 'TOTAL SEMESTER SESSIONS', 'SESSIONS DONE', 'TOTAL PRESENT', 'ATTENDANCE %', 'ATTENDANCE SEMESTER %', 'PROJECTED ATTENDANCE SEMESTER %', 'ELIGIBLE', 'INDIRECT FAIL']

            # Save the aggregated DataFrame
            aggregated_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'nim_course_aggregate.csv')
            df.to_csv(aggregated_file_path, index=False, sep=";")

            # Further processing for NIM table
            # Find number of unique course codes for each student
            enrolled_courses = df.groupby('NIM')['COURSE CODE'].nunique().reset_index()
            enrolled_courses.columns = ['NIM', 'NUMBER OF ENROLLED COURSES']

            # Find number of failed courses with unique course codes
            failed_courses = df[df['ELIGIBLE'] == False].groupby('NIM')['COURSE CODE'].nunique().reset_index()
            failed_courses.columns = ['NIM', 'NUMBER OF FAILED COURSES']

            # Merge results to create a NIM, number of enrolled courses, and number of failed courses table
            grouped_nim = enrolled_courses.merge(failed_courses, on='NIM', how='left').fillna(0)

            # fillna forces column into float, so converting back to int
            grouped_nim['NUMBER OF FAILED COURSES'] = grouped_nim['NUMBER OF FAILED COURSES'].astype(int)

            # Calculate the percentage of failed courses
            grouped_nim['PERCENTAGE OF FAILED COURSES'] = round(((grouped_nim['NUMBER OF FAILED COURSES'] / grouped_nim['NUMBER OF ENROLLED COURSES']) * 100), 2)

            # Merge grouped_nim with NAME and MAJOR columns
            grouped_nim = df[['NIM', 'NAME', 'MAJOR']].drop_duplicates().merge(grouped_nim, on='NIM', how='left')

            # Reorder columns
            grouped_nim.columns = ['NIM', 'NAME', 'MAJOR', 'NUMBER OF ENROLLED COURSES', 'NUMBER OF FAILED COURSES', 'PERCENTAGE OF FAILED COURSES']

            # Save the GROUPBY NIM table
            nim_aggregated_file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'nim_aggregate.csv')
            grouped_nim.to_csv(nim_aggregated_file_path, index=False, sep=";")

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
        attendance = (1 - (df.groupby('NIM')['TOTAL ABSENCE'].sum() / df.groupby('NIM')['SESSION DONE'].sum())) * 100
    elif divisor == 'Projected':
        # Calculate projected attendance
        attendance = (1 - (df.groupby('NIM')['TOTAL ABSENCE'].sum() / df.groupby('NIM')['TOTAL SESSION'].sum())) * 100
    else:
        return jsonify({'error': 'Invalid divisor for attendance calculation'})

    print(attendance)
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
        attendance = (1 - (df.groupby('NIM')['TOTAL ABSENCE'].sum() / df.groupby('NIM')['SESSION DONE'].sum())) * 100
    elif divisor == 'Projected':
        # Calculate projected attendance
        attendance = (1 - (df.groupby('NIM')['TOTAL ABSENCE'].sum() / df.groupby('NIM')['TOTAL SESSION'].sum())) * 100

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

        # If the student isn't in the semester, move on to the next one
        if student_rows.empty:
            results[current_semester] = 0
            not_enrolled.append(current_semester)
            continue  
        
        # Get student's name if it doesn't exist
        if student_name is None:
            student_name = student_rows.iloc[0]['NAME']

        if divisor == 'Max':
            below_threshold = (student_rows['TOTAL ABSENCE'] > student_rows['MAX ABSENCE']).sum()
        else:
            if divisor == 'Present':
            # Calculate attendance percentage
                attendance = (1 - (student_rows['TOTAL ABSENCE'] / student_rows['SESSION DONE'])) * 100
            elif divisor == 'Projected':
                # Calculate projected attendance
                attendance = (1 - (student_rows['TOTAL ABSENCE'] / student_rows['TOTAL SESSION'])) * 100

            below_threshold = (attendance < threshold).sum()

        results[current_semester] = int(below_threshold)
    
    if not bool(results):
        return jsonify({'error': 'Student not found in any semester.'})
    
    # Sorting the dictionary so the semesters are in chronological order
    results_sorted = {semester: results[semester] for semester in sorted(results.keys(), key=semester_sort)}

    # Finding the first semester where the student is enrolled
    first_enrolled_semester = next((s for s in results_sorted.keys() if s not in not_enrolled), None)

    if first_enrolled_semester is None:
        return jsonify({'error': 'Student not found in any semester.'})

    # Remove all semesters before it
    results_sorted = {s: c for s, c in results_sorted.items() if semester_sort(s) >= semester_sort(first_enrolled_semester)}

    if len(results_sorted) < 21:
        return jsonify({"name": student_name, "not_enrolled": not_enrolled, "data": [{"semester": s, "count": c} for s, c in results_sorted.items()]})
    else:
        return jsonify({"name": student_name, "not_enrolled": not_enrolled, "data": [{"semester": s, "count": c} for s, c in list(results_sorted.items())[-21:]]})


@app.route('/get_bar_chart_course_data', methods=['POST'])
def get_bar_chart_course_data():
    data = request.get_json()
    course = data.get('course')
    components = data.get('components')
    value = data.get('value')
    semester_count = data.get('semester_count')
    threshold = data.get('threshold')
    divisor = data.get('divisor')

    # If LEC/LAB is picked, query both LEC and LAB
    if "LEC/LAB" in components:
        components.remove("LEC/LAB")
        components.extend(["LEC", "LAB"])

    # Track if course has LAB
    course_has_lab = False

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

        # A dictionary to store the attendance per component per semester
        semester_results = {'LEC/LAB': set(), 'EXL': None, 'BLK': None}

        students_in_lec_and_lab = None

        data_found = False

        for component in components:
            # Show the correct component
            comp_rows = course_rows[course_rows['COMPONENT']== component]

            # If the course isn't in the semester, move on to next component
            if comp_rows.empty:
                continue  
            
            # If there's a single instance of comp_rows not being empty, the selected compoonents exist
            if not data_found:
                data_found = True

            # Check for lab
            if component == "LAB":
                course_has_lab = True

            # Get coursename if it doesn't exist
            if course_name is None:
                course_name = comp_rows.iloc[0]['COURSE NAME']
            
            if divisor == 'Max':
                # Get NIM for all students where total absence ? max absence
                failing_students = set(comp_rows.loc[comp_rows['TOTAL ABSENCE'] > comp_rows['MAX ABSENCE'], 'NIM'])
            else:
                if divisor == 'Present':
                    # Calculate attendance percentage
                    attendance = (1 - (comp_rows['TOTAL ABSENCE'] / comp_rows['SESSION DONE'])) * 100
                elif divisor == 'Projected':
                    # Calculate projected attendance
                    attendance = (1 - (comp_rows['TOTAL ABSENCE'] / comp_rows['TOTAL SESSION'])) * 100
                
                attendance.index = comp_rows['NIM']

                # Get student NIMs who are below the threshold
                failing_students = set(attendance[attendance < threshold].index)

            # print(failing_students)

            # Converting to percentage of students
            if value == 'Percentage':
                num_of_students = comp_rows['NIM'].nunique()
                below_threshold = round((len(failing_students) / num_of_students * 100), 2) if num_of_students > 0 else 0
            else: 
                below_threshold = len(failing_students)
            
            # Store results fr LEC and LAB components
            if component in ["LEC", "LAB"]:
                if students_in_lec_and_lab is None:
                    students_in_lec_and_lab = comp_rows['NIM'].nunique()
                semester_results["LEC/LAB"].update(failing_students)  # Add all students below threshold to the set for LEC/LAB
            else:
                semester_results[component] = below_threshold

        # Convert LEC/LAB from set to count of unique students. If no students, return 'N/A', else calculate results based on percentage of number
        if students_in_lec_and_lab is None:
            semester_results["LEC/LAB"] = "N/A"
        elif value == 'Percentage':
            semester_results['LEC/LAB'] = round((len(semester_results['LEC/LAB']) / students_in_lec_and_lab * 100), 2) if students_in_lec_and_lab > 0 else 0
        else:
            semester_results['LEC/LAB'] = len(semester_results['LEC/LAB'])

        results[current_semester] = semester_results
    
    if not data_found:
        return jsonify({'error': 'Course not found in any semester.'})
    
    # Sorting the dictionary so the semesters are in chronological order
    results_sorted = {semester: results[semester] for semester in sorted(results.keys(), key=semester_sort)}

    # Limit to semester_count semesters
    if len(results_sorted) > int(semester_count):
        results_sorted = dict(list(results_sorted.items())[-int(semester_count):])

    # Convert results to the appropriate format for chart.js to understand
    formatted_results = []
    for semester, counts in results_sorted.items():
        semester_data = []

        # LEC/LAB, doesn't matter which one the if statement checks since there's only one combined option in frontend
        # And the code above adds both LEC and LAB to components if that was chosen
        if "LEC" in components:
            semester_data.append({
                "component": "LEC/LAB" if course_has_lab else "LEC",
                "count": counts["LEC/LAB"]
            })

        # EXL & BLK
        for comp in ["EXL", "BLK"]:
            if comp in components:
                semester_data.append({
                    "component": comp,
                    "count": counts[comp] if counts[comp] is not None else 'N/A' # If course component doesn't exist, return N/A
                })

        formatted_results.append({
            "semester": semester,
            "data": semester_data
        })

    return jsonify({"name": course_name, "data": formatted_results})

@app.route('/get_bar_chart_student_course_data', methods=['POST'])
def get_bar_chart_student_course_data():
    data = request.get_json()
    nim = data.get('nim')
    course = data.get('course')
    component = data.get('component')
    value = data.get('value')
    max_semesters = data.get('semesters')

    # Query all tables in the database, one for each semester
    all_entries = AttendanceFile.query.all()

    # Dictionary to store results, and variable to store student name
    results = {}
    not_enrolled = []
    course_name = None
    student_name = None

    checked_csvs = 0

    # Loop through all tables
    for entry in all_entries:
        # Construct the current entry's semester
        current_semester = f"{entry.semester_type} {entry.year}"

        # Load CSV
        df = pd.read_csv(io.BytesIO(entry.csv_file), delimiter=";", encoding="Windows-1252")

        # Update count of checked CSVs
        checked_csvs += 1

        # Only show selected student
        student_rows = df[df['NIM'] == int(nim)]

        # Only show selected course
        course_rows = student_rows[student_rows['COURSE CODE'] == course]

        # Only show selected component
        course_rows = course_rows[course_rows['COMPONENT'] == component]

        # If the course isn't in the semester, move on to the next one
        if course_rows.empty:
            results[current_semester] = 0
            not_enrolled.append(current_semester)
            continue
        
        # Get coursename if it doesn't exist
        if course_name is None or student_name is None:
            course_name = course_rows.iloc[0]['COURSE NAME']
            student_name = course_rows.iloc[0]['NAME']

        # Calculate number of present sessions
        attendance = course_rows['SESSION DONE'] - course_rows['TOTAL ABSENCE']

        if value == 'Percentage':
            sessions = course_rows['SESSION DONE']
            results[current_semester] = round((int(attendance.iloc[0]) / int(sessions.iloc[0]) * 100), 2)
        
        else:
            results[current_semester] = int(attendance.iloc[0])


    if len(not_enrolled) == checked_csvs:
        return jsonify({'error': 'Course and student combination not found in any semester.'})
    
    # Sorting the dictionary so the semesters are in chronological order
    results_sorted = {semester: results[semester] for semester in sorted(results.keys(), key=semester_sort)}

    if len(results_sorted) > max_semesters:
        # Keep the most recent x semesters, according to the max_semesters variable
        max_results = dict(list(results_sorted.items())[-max_semesters:])
    else:
        max_results = results_sorted

    # Finding the first semester where the student is enrolled
    first_enrolled_semester = next((s for s in results_sorted.keys() if s not in not_enrolled), None)

    if first_enrolled_semester is None:
        return jsonify({'error': 'Student not found in any semester.'})
    
    # Continuously check if the oldest semester currently returned needs to be removed or not
    while (oldest_returned := next(iter(max_results.keys()), None)) in not_enrolled:
        if semester_sort(oldest_returned) < semester_sort(first_enrolled_semester):
            del max_results[oldest_returned]
            not_enrolled.remove(oldest_returned)
        else:
            break 

    return jsonify({"course_name": course_name, "student_name": student_name, "not_enrolled": not_enrolled, "data": [{"semester": s, "count": c} for s, c in max_results.items()]})



if __name__ == '__main__':
    app.run(debug=True)
