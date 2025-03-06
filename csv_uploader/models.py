import pandas as pd # type: ignore
import random

# Specify the file name here
file_name = r'''C:\Users\Brandon Salim\Desktop\Data\Mockdata Attendance 24.2 sd 11-01-2018.csv'''

try:
    # Load CSV into DataFrame
    df = pd.read_csv(file_name)

    # Check if 'PRESENT' column exists
    if 'PRESENT' in df.columns:
        # Generate a random threshold between 1 and 100
        threshold = random.randint(1, 100)

        # Assign 'Y' or 'N' based on the threshold
        df['PRESENT'] = df['PRESENT'].apply(lambda _: 'Y' if random.randint(1, 100) > threshold else 'N')
        
        # Save the modified DataFrame
        df.to_csv(file_name, index=False)
        
        print(f"File saved.")

    else:
        print("Error: 'PRESENT' column not found in the CSV.")

except FileNotFoundError:
    print("Error: File not found. Check the file name and try again.")
