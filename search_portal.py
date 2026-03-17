import pandas as pd
import streamlit as st
import os

st.title("UPC / LP Search Portal")

# --- Folders ---
ref_folder = "reference"   # Folder with Excel files
csv_folder = "reference_csv"  # Folder for converted CSVs
output_folder = "output"   # For search results
os.makedirs(csv_folder, exist_ok=True)
os.makedirs(output_folder, exist_ok=True)

# --- Step 1: Convert Excel to CSV if not already ---
for file in os.listdir(ref_folder):
    if file.endswith((".xlsx", ".xls")) and not file.startswith("~$"):
        csv_name = os.path.splitext(file)[0] + ".csv"
        csv_path = os.path.join(csv_folder, csv_name)
        if not os.path.exists(csv_path):  # only convert if CSV doesn't exist
            df = pd.read_excel(os.path.join(ref_folder, file))
            df = df.dropna(how="all")
            df = df.dropna(axis=1, how="all")
            df.to_csv(csv_path, index=False)

# --- Step 2: List available CSV reference files ---
available_files = [f for f in os.listdir(csv_folder) if f.endswith(".csv")]
selected_files = st.multiselect("Select reference file(s) to search", available_files, default=available_files)

if not selected_files:
    st.warning("Please select at least one reference file")
    st.stop()

# --- Step 3: Load selected CSV files ---
ref_dfs = []
for file in selected_files:
    df = pd.read_csv(os.path.join(csv_folder, file))
    # Clean columns
    df['Case UPC'] = df['Case UPC'].astype(str).str.zfill(5).str.strip()
    df['DBW Group'] = df['DBW Group'].astype(str).str.strip()
    ref_dfs.append(df)

database = pd.concat(ref_dfs, ignore_index=True)
st.write(f"Loaded reference database: {len(database)} rows")

# --- Step 4: User input ---
upc_input = st.text_input("Enter UPC (optional)")
lp_input = st.text_input("Enter LP (optional)")
# upc_list = [str(u).strip().zfill(5) for u in upc_input.split(",") if u.strip()]
# lp_list = [str(l).strip() for l in lp_input.split(",") if l.strip()]

# --- Step 5: Search on button click ---
if st.button("Search"):
    if not upc_input and not lp_input:
        st.warning("Please enter at least UPC or LP")
    else:
        df_search = database.copy()
        if upc_input:
            df_search = df_search[df_search["Case UPC"].str.contains(str(upc_input).strip().zfill(5), na=False)]
        if lp_input:
            df_search = df_search[df_search["DBW Group"].str.contains(str(lp_input).strip(), na=False)]
        # if upc_list:
        #     df_search = df_search[df_search["Case UPC"].isin(upc_list)]
        # if lp_list:
        #     df_search = df_search[df_search["Primary PG"].isin(lp_list)]
        if df_search.empty:
            st.info("No matching results found")
        else:
            st.dataframe(df_search)
            # Export CSV
            csv_name = "search_result.csv"
            df_search.to_csv(os.path.join(output_folder, csv_name), index=False)
            st.success(f"Search results saved to {os.path.join(output_folder, csv_name)}")