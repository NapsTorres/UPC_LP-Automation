import pandas as pd
import streamlit as st
import os

st.title("UPC / LP Search Portal")

# --- Folders ---
ref_folder = "reference"   # Hostess + JMSMUC reference files
output_folder = "output"   # Optional: for saving search results
os.makedirs(output_folder, exist_ok=True)

# --- Load all reference files ---
ref_dfs = []
for file in os.listdir(ref_folder):
    if file.endswith(".xlsx") or file.endswith(".xls"):
        df = pd.read_excel(os.path.join(ref_folder, file))
        df = df.dropna(how="all")         # remove empty rows
        df = df.dropna(axis=1, how="all") # remove empty columns
        ref_dfs.append(df)

if not ref_dfs:
    st.error("No reference files found in 'reference/' folder!")
    st.stop()

database = pd.concat(ref_dfs, ignore_index=True)
st.write(f"Loaded reference database: {len(database)} rows")

# --- List available reference files ---
available_files = [f for f in os.listdir(ref_folder) if f.endswith((".xlsx", ".xls")) and not f.startswith("~$")]

# Show dropdown or multiselect
selected_files = st.multiselect("Select reference file(s) to search", available_files, default=available_files)
# --- Input fields ---
upc_input = st.text_input("Enter UPC (optional)")
lp_input = st.text_input("Enter LP (optional)")

# --- Clean database columns ---
database['Case UPC'] = database['Case UPC'].astype(str).str.zfill(5).str.strip()
database['Primary PG'] = database['Primary PG'].astype(str).str.strip()

# --- Clean user input ---
upc_input = str(upc_input).strip().zfill(5)  # pad with zeros to 5 digits
lp_input = str(lp_input).strip()

if st.button("Search"):
    if not upc_input and not lp_input:
        st.warning("Please enter at least UPC or LP")
    else:
        df = database.copy()
# --- Filter by UPC and LP ---
if upc_input:
    df = df[df["Case UPC"].str.contains(upc_input, na=False)]
if lp_input:
    df = df[df["Primary PG"].str.contains(lp_input, na=False)]

if df.empty:
    st.info("No matching results found")
else:
    st.dataframe(df)

    # --- Optional: Export button ---
    csv_name = f"search_result.csv"
    df.to_csv(os.path.join(output_folder, csv_name), index=False)
    st.success(f"Search results saved to {os.path.join(output_folder, csv_name)}")