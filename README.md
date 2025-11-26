# Add Parameters to Revit Types (ACC Integration)

A VIKTOR app that automates adding custom parameters to Revit model types and exporting to IFC format, using Autodesk Construction Cloud (ACC) and Design Automation API.

## Features

### Step 1: Add Parameters to Revit Types

Upload your Revit file, define custom parameters in a table, and automatically add them to specific element types and families.

![Step 1 - Add Parameters](assets/STEP1.jpg)

### Step 2: Export to IFC

Select views from your updated model and export them to IFC format for downstream use.

![Step 2 - IFC Export](assets/STEP2.jpg)

## Prerequisites

- VIKTOR platform account
- Autodesk Platform Services (APS) credentials
- Access to Autodesk Construction Cloud (ACC)

## Setup

### 1. Create a New APS Application

For the integration with ACC, you need a clean APS application without any existing Design Automation resources. If you have previous activities or app bundles, you'll need to remove them first or create a new application.

Create a new application following the official guide:  
[Create an APS Application](https://aps.autodesk.com/en/docs/oauth/v2/tutorials/create-app/)

### 2. Create Environment File

Create a `.env` file in the project root and add your APS credentials:

```env
CLIENT_ID=your_client_id_here
CLIENT_SECRET=your_client_secret_here
```

### 3. Generate Keys and Upload Public Key

Refer to **Step 1** and **Step 2** in `autodesk_automation - ACC/automation_signing_guide.ipynb`. This notebook contains all the steps to create signed workitems.

In general, you will need to:
1. Generate a secret key pair (private + public key) using the official [Das.WorkItemSigner](https://github.com/autodesk-platform-services/aps-designautomation-signer/releases)
2. Upload the public key to your APS app

> **Note**: You can run this notebook outside the repo. If running inside this repo, use `uv` to install the `requirements.txt` and add that venv to the notebook. Alternatively, run `viktor-cli install` and activate the created venv (`source .venv/bin/activate` or `.\.venv\Scripts\Activate.ps1` on Windows).

### 4. Create Design Automation Activities

Create the two automations by following the respective notebooks:

1. **Add Parameters to Type Activity**  
   Follow: `autodesk_automation - ChangeTypes/create_activities_by_revit_version.ipynb`

2. **Export to IFC Activity**  
   Follow: `autodesk_automation - ExportIFC/create_activities_by_revit_version.ipynb`

### 5. Add Activity Full Aliases to .env

Add your activity full aliases to the `.env` file using your real nickname and alias from the notebooks:

```env
ACTIVITY_FULL_ALIAS_TypeParameters2023 = "<nickname>.TypeParametersActivity2023+<alias>"
ACTIVITY_FULL_ALIAS_TypeParameters2024 = "<nickname>.TypeParametersActivity2024+<alias>"
# ... add all versions (2023-2026) for both activities
```

See `.env.sample` for the complete list of required variables.

### 6. Sign Activities

Use your activity aliases to create signed activity names by following **Step 3** in `autodesk_automation - ACC/automation_signing_guide.ipynb`.

Run the signer tool for each activity:
```powershell
.\Das.WorkItemSigner.exe sign mykey.json <nickname>.TypeParametersActivity2023+<alias>
.\Das.WorkItemSigner.exe sign mykey.json <nickname>.RevitIfcExportAppActivity2023+<alias>
# ... repeat for all versions (2023-2026)
```

### 7. Add Activity Signatures to .env

Add the generated signatures for each activity to your `.env` file:

```env
TypeParametersActivity2023 = "<signature>"
TypeParametersActivity2024 = "<signature>"
# ... add all signatures
```

### 8. Set Up VIKTOR APS Integration

The VIKTOR admin should set up the APS integration following:  
[VIKTOR - Autodesk Platform Services Integration](https://docs.viktor.ai/docs/create-apps/software-integrations/autodesk-platform-services/)

> **Important**: The `CLIENT_ID` and `CLIENT_SECRET` of the integration **must match** the ones from the APS application that created the activities and signed them.

### 9. Configure VIKTOR Integration Name

Add the integration name of your VIKTOR APS integration in `viktor.config.toml`.

### 10. Update Controller Integration Name

Change the integration name in `app/controller.py` to match your VIKTOR integration name.

### 11. Add Client ID to ACC Hubs

Add the APS application's client ID to the ACC hubs you want to integrate with the app:  
[VIKTOR - Autodesk Construction Cloud Integration](https://docs.viktor.ai/docs/create-apps/software-integrations/autodesk-construction-cloud/)

### 12. Install Dependencies

Run the VIKTOR CLI to install dependencies:

```bash
viktor-cli install
```

## Supported Revit Versions

- Revit 2023
- Revit 2024
- Revit 2025
- Revit 2026

The app automatically detects the Revit version from the uploaded model and uses the corresponding activity.

## Usage

1. **Step 1 - Add Parameters**
   - Select your Revit file from ACC
   - Configure the parameter table with:
     - Parameter Name
     - Parameter Group
     - Type Name
     - Family Name
     - Value
   - Click "Run Automation" to process

2. **Step 2 - IFC Export**
   - Select the updated Revit file
   - Choose views to export
   - Click "Export to IFC"