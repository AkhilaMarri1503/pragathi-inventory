import pandas as pd
import numpy as np
from itertools import product

# ------------------------------------------------------------
# 1. Load and clean data
# ------------------------------------------------------------
# Read the Excel file - Sheet1, skip first few rows until we find the header row
# Based on your file, the actual data starts at row 4 (0-indexed row 3)
df_raw = pd.read_excel('SCHOOL STOCK.xlsx', sheet_name='Sheet1', skiprows=3)

# Rename columns to match our needs (your columns: Branch, Product, Brand, Artical, Size, Colour, Mrp, CLQTY, CLVAL, Note)
df_raw.columns = ['Branch', 'Product', 'Brand', 'Article', 'Size', 'Colour', 'Mrp', 'CLQTY', 'CLVAL', 'Note']

# Remove any rows where Branch is NaN or empty (like the last summary row)
df_raw = df_raw.dropna(subset=['Branch'])
df_raw = df_raw[df_raw['Branch'].str.strip() != '']

# Convert CLQTY to integer
df_raw['Quantity'] = pd.to_numeric(df_raw['CLQTY'], errors='coerce').fillna(0).astype(int)

# Keep only needed columns
df = df_raw[['Branch', 'Product', 'Brand', 'Article', 'Size', 'Colour', 'Quantity']].copy()

# ------------------------------------------------------------
# 2. Filter out PARAGON brand
# ------------------------------------------------------------
df = df[~df['Brand'].str.contains('PARAGON', case=False, na=False)]

# ------------------------------------------------------------
# 3. Identify all unique branches and all unique SKUs
#    SKU = (Product, Brand, Article, Size, Colour)
# ------------------------------------------------------------
branches = sorted(df['Branch'].unique())
sku_columns = ['Product', 'Brand', 'Article', 'Size', 'Colour']
all_skus = df[sku_columns].drop_duplicates().values.tolist()

# Create a complete DataFrame with every branch-SKU combination
full_index = pd.MultiIndex.from_product([branches, range(len(all_skus))], names=['Branch', 'SKU_id'])
full_df = pd.DataFrame(index=full_index).reset_index()

# Map SKU_id back to SKU values
sku_df = pd.DataFrame(all_skus, columns=sku_columns)
sku_df['SKU_id'] = sku_df.index

full_df = full_df.merge(sku_df, on='SKU_id', how='left')
full_df = full_df.drop(columns=['SKU_id'])

# Merge actual quantities
actual = df.groupby(['Branch'] + sku_columns)['Quantity'].sum().reset_index()
full_df = full_df.merge(actual, on=['Branch'] + sku_columns, how='left')
full_df['Quantity'] = full_df['Quantity'].fillna(0).astype(int)

# ------------------------------------------------------------
# 4. Calculate Required Stock (Need) per branch-SKU
# ------------------------------------------------------------
def is_popular_branch(branch_name):
    return 'POPULAR' in branch_name.upper()

full_df['Need'] = full_df['Branch'].apply(lambda b: 12 if is_popular_branch(b) else 6)

# ------------------------------------------------------------
# 5. Compute surplus and shortfall
# ------------------------------------------------------------
full_df['Shortfall'] = full_df['Need'] - full_df['Quantity']
full_df['Shortfall'] = full_df['Shortfall'].clip(lower=0)
full_df['Surplus'] = full_df['Quantity'] - full_df['Need']
full_df['Surplus'] = full_df['Surplus'].clip(lower=0)

# ------------------------------------------------------------
# 6. Generate inter-branch transfers (greedy)
#    For each SKU, move surplus from branches to cover shortfall in others
# ------------------------------------------------------------
transfer_records = []
for sku in sku_df[sku_columns].itertuples(index=False):
    sku_dict = {col: getattr(sku, col) for col in sku_columns}
    # Get shortfall and surplus for this SKU
    mask = (full_df[sku_columns] == pd.Series(sku_dict)).all(axis=1)
    sku_data = full_df[mask].copy()
    # Create lists of (branch, surplus) and (branch, shortfall)
    surplus_list = sku_data[sku_data['Surplus'] > 0][['Branch', 'Surplus']].values.tolist()
    shortfall_list = sku_data[sku_data['Shortfall'] > 0][['Branch', 'Shortfall']].values.tolist()
    # Greedy matching
    i, j = 0, 0
    while i < len(surplus_list) and j < len(shortfall_list):
        surp_branch, surp_qty = surplus_list[i]
        short_branch, short_qty = shortfall_list[j]
        transfer = min(surp_qty, short_qty)
        if transfer > 0:
            transfer_records.append({
                'Source': surp_branch,
                'Destination': short_branch,
                'Product': sku_dict['Product'],
                'Brand': sku_dict['Brand'],
                'Article': sku_dict['Article'],
                'Size': sku_dict['Size'],
                'Colour': sku_dict['Colour'],
                'Quantity': transfer
            })
            surplus_list[i][1] -= transfer
            shortfall_list[j][1] -= transfer
        if surplus_list[i][1] == 0:
            i += 1
        if shortfall_list[j][1] == 0:
            j += 1

transfers_df = pd.DataFrame(transfer_records)

# ------------------------------------------------------------
# 7. Prepare per-branch sheets
# ------------------------------------------------------------
output_file = 'Inventory_Report.xlsx'
writer = pd.ExcelWriter(output_file, engine='openpyxl')

for branch in branches:
    # Available Stock: all SKUs with actual quantity (including zeros)
    avail = full_df[full_df['Branch'] == branch][['Product', 'Brand', 'Article', 'Size', 'Colour', 'Quantity']].copy()
    avail.loc[len(avail)] = ['GRAND TOTAL', '', '', '', '', avail['Quantity'].sum()]
    avail.to_excel(writer, sheet_name=f'{branch} - Available Stock', index=False)

    # Required Stock: Need column
    req = full_df[full_df['Branch'] == branch][['Product', 'Brand', 'Article', 'Size', 'Colour', 'Need']].copy()
    req.loc[len(req)] = ['GRAND TOTAL', '', '', '', '', req['Need'].sum()]
    req.to_excel(writer, sheet_name=f'{branch} - Required Stock', index=False)

    # Outgoing Transfers: where Source == branch
    outgoing = transfers_df[transfers_df['Source'] == branch].copy()
    if not outgoing.empty:
        outgoing = outgoing[['Destination', 'Product', 'Brand', 'Article', 'Size', 'Colour', 'Quantity']]
        outgoing.loc[len(outgoing)] = ['GRAND TOTAL', '', '', '', '', '', outgoing['Quantity'].sum()]
    else:
        outgoing = pd.DataFrame(columns=['Destination', 'Product', 'Brand', 'Article', 'Size', 'Colour', 'Quantity'])
        outgoing.loc[0] = ['GRAND TOTAL', '', '', '', '', '', 0]
    outgoing.to_excel(writer, sheet_name=f'{branch} - Outgoing Transfers', index=False)

    # Incoming Transfers: where Destination == branch
    incoming = transfers_df[transfers_df['Destination'] == branch].copy()
    if not incoming.empty:
        incoming = incoming[['Source', 'Product', 'Brand', 'Article', 'Size', 'Colour', 'Quantity']]
        incoming.loc[len(incoming)] = ['GRAND TOTAL', '', '', '', '', '', incoming['Quantity'].sum()]
    else:
        incoming = pd.DataFrame(columns=['Source', 'Product', 'Brand', 'Article', 'Size', 'Colour', 'Quantity'])
        incoming.loc[0] = ['GRAND TOTAL', '', '', '', '', '', 0]
    incoming.to_excel(writer, sheet_name=f'{branch} - Incoming Transfers', index=False)

# Optional: add a summary sheet of all transfers
if not transfers_df.empty:
    all_transfers = transfers_df[['Source', 'Destination', 'Product', 'Brand', 'Article', 'Size', 'Colour', 'Quantity']].copy()
    all_transfers.loc[len(all_transfers)] = ['GRAND TOTAL', '', '', '', '', '', '', all_transfers['Quantity'].sum()]
else:
    all_transfers = pd.DataFrame(columns=['Source', 'Destination', 'Product', 'Brand', 'Article', 'Size', 'Colour', 'Quantity'])
    all_transfers.loc[0] = ['GRAND TOTAL', '', '', '', '', '', '', 0]
all_transfers.to_excel(writer, sheet_name='All Transfers (Summary)', index=False)

writer.close()
print(f"✅ Report generated: {output_file}")
print(f"   Branches processed: {len(branches)}")
print(f"   Total inter-branch transfers: {len(transfer_records)}")
