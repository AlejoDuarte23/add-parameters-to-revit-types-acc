import base64
import json
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Any, Dict

import requests
import viktor as vkt
from aps_automation_sdk.acc import parent_folder_from_item
from aps_automation_sdk.classes import (
    ActivityInputParameterAcc,
    ActivityJsonParameter,
    ActivityOutputParameterAcc,
    WorkItemAcc,
)
from dotenv import load_dotenv

from app.helpers import (
    DEFAULT_REVIT_VERSION,
    create_ifc_export_json,
    fetch_manifest,
    get_ifc_export_signature,
    get_revit_version_from_manifest,
    get_type_parameters_signature,
    get_view_names_from_manifest,
    get_viewables_from_urn,
)

load_dotenv()

DA_V3 = "https://developer.api.autodesk.com/da/us-east/v3"


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def get_workitem_status(wi_id: str, token: str) -> Dict[str, Any]:
    url = f"{DA_V3}/workitems/{wi_id}"
    r = requests.get(url, headers=bearer(token), timeout=30)
    r.raise_for_status()
    return r.json()


@vkt.memoize
def get_view_names_for_file(*, version_urn: str) -> list[str]:
    """
    Memoized function to get view names from an Autodesk file.
    Uses version_urn as cache key.
    """
    try:
        integration = vkt.external.OAuth2Integration("aps-integration-design")
        token = integration.get_access_token()
        encoded_urn = base64.urlsafe_b64encode(version_urn.encode()).decode().rstrip("=")
        manifest_url = f"https://developer.api.autodesk.com/modelderivative/v2/designdata/{encoded_urn}/manifest"
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(manifest_url, headers=headers, timeout=30)
        resp.raise_for_status()
        manifest = resp.json()
        return get_view_names_from_manifest(manifest)
    except Exception as e:
        print(f"Error getting view names: {e}")
        return []


def get_view_names_options(params, **kwargs) -> list:
    """Callback for MultiSelectField to get available view names as OptionListElements."""
    autodesk_file = params.step_ifc.visualize.output_file
    if not autodesk_file:
        return []
    print("Inside")

    integration = vkt.external.OAuth2Integration("aps-integration-design")
    token = integration.get_access_token()
    version = autodesk_file.get_latest_version(token)
    
    view_names = get_view_names_for_file(version_urn=version.urn)
    print(f"{view_names=}")
    
    return [vkt.OptionListElement(label=name, value=name) for name in view_names]


class Parametrization(vkt.Parametrization):
    # Step 1: Add Parameters to Revit Types
    step_params = vkt.Step("Add Parameters", views=["aps_view"])
    step_params.inputs = vkt.Section("Inputs")
    step_params.inputs.intro = vkt.Text("""# Add Parameters to Revit Types
This app helps you add custom parameters to your Revit model elements automatically. 
Upload your Revit file, define which parameters you want to add and which elements should get them, then view the results in 3D.""")
    step_params.inputs.input_file = vkt.AutodeskFileField("Select Your Revit File", oauth2_integration="aps-integration-design")
    
    step_params.table_section = vkt.Section("Parameter Table")
    step_params.table_section.intro = vkt.Text("""## Parameter Configuration
In this table, you define what parameters to add to which elements in your Revit model. 
Each row specifies a parameter name (like "Carbon_Rating"), the element type and family it should be added to, 
and the value to set. You can add multiple rows with the same parameter name to apply it to different elements.""")
    step_params.table_section.targets = vkt.Table("Targets", default=[
        {
            "parameter_name": "Carbon_Dataset_Code",
            "parameter_group": "PG_DATA",
            "type_name": "400x400mm",
            "family_name": "CO_01_001_Geheide_prefab_betonpaal",
            "value": "95"
        }
    ])
    step_params.table_section.targets.parameter_name = vkt.TextField("Parameter Name")
    step_params.table_section.targets.parameter_group = vkt.OptionField(
        "Parameter Group",
        options=["PG_TEXT", "PG_DATA", "PG_IDENTITY_DATA", "PG_GEOMETRY"]
    )
    step_params.table_section.targets.type_name = vkt.TextField("Type Name")
    step_params.table_section.targets.family_name = vkt.TextField("Family Name")
    step_params.table_section.targets.value = vkt.TextField("Value")
    
    step_params.action = vkt.Section("Run Automation")
    step_params.action.intro = vkt.Text("""## Run Automation
Click the button below to generate the updated Revit model with your custom parameters. 
The automation will process your file and add all specified parameters to the target element types.""")
    step_params.action.button = vkt.ActionButton("Run Automation", method="process_with_workitem")
    
    # Step 2: IFC Export
    step_ifc = vkt.Step("IFC Export", views=["aps_view_step2"])
    
    step_ifc.visualize = vkt.Section("Visualize Output File")
    step_ifc.visualize.intro = vkt.Text("""## View Updated Model
Use the Autodesk file field below to display the updated model with the added type parameters. 
After running the automation in Step 1, select the generated output file to visualize and verify that your parameters were successfully added to the Revit types.""")
    step_ifc.visualize.output_file = vkt.AutodeskFileField("Select Updated Revit File", oauth2_integration="aps-integration-design")
    
    step_ifc.inputs = vkt.Section("IFC Export Settings")
    step_ifc.inputs.intro = vkt.Text("""## Export to IFC
Select one or more views from the model above to export to IFC format.""")
    step_ifc.inputs.selected_views_for_ifc = vkt.MultiSelectField(
        "Select view(s) to export to IFC",
        options=get_view_names_options,
        description="Select one or more views to export to IFC format"
    )
    step_ifc.inputs.export_ifc_button = vkt.ActionButton("Export to IFC", method="export_to_ifc")

class APSResult(vkt.WebResult):
    """Custom WebResult that renders an APS Viewer with viewable selection."""
    
    def __init__(self, urn: Annotated[str, "base64 encoded URN"], token: str):
        # Get viewables from the translated model
        viewables = []
        if urn:
            try:
                viewables = get_viewables_from_urn(token, urn)
            except Exception as e:
                print(f"Warning: Could not fetch viewables: {e}")
        
        html = (Path(__file__).parent / "ViewableViewer.html").read_text()
        html = html.replace("APS_TOKEN_PLACEHOLDER", token)
        html = html.replace("URN_PLACEHOLDER", urn)
        html = html.replace("VIEWABLES_PLACEHOLDER", json.dumps(viewables))
        super().__init__(html=html)


class Controller(vkt.Controller):
    parametrization = Parametrization
    
    @vkt.WebView("APS Viewer", duration_guess=10)
    def aps_view(self, params, **kwargs):
        integration = vkt.external.OAuth2Integration("aps-integration-design")
        token = integration.get_access_token()
        
        autodesk_file = params.step_params.inputs.input_file
        if not autodesk_file:
            raise vkt.UserError("Please select a model in the Autodesk file field")
        
        # Get the URN and encode it
        version = autodesk_file.get_latest_version(token)
        urn = version.urn
        encoded_urn = base64.urlsafe_b64encode(urn.encode()).decode().rstrip("=")
        
        # Try to fetch manifest and extract Revit version from Model Derivative
        try:
            manifest = fetch_manifest(params.step_params.inputs.input_file, token)
            vkt.UserMessage.info(f"Manifest status: {manifest.get('status', 'unknown')}")
            
            # Extract Revit version directly from manifest
            revit_version = get_revit_version_from_manifest(manifest)
            print(f"Revit Version: {revit_version}")
            if revit_version:
                vkt.UserMessage.info(f"Revit Version: {revit_version}")
            else:
                vkt.UserMessage.info("Note: Could not extract Revit version from manifest")
        except Exception as e:
            print(f"Error retrieving model info: {str(e)}")
            vkt.UserMessage.info(f"Note: Could not retrieve model info: {str(e)}")
        
        return APSResult(urn=encoded_urn, token=token)

    @vkt.WebView("APS Viewer", duration_guess=10)
    def aps_view_step2(self, params, **kwargs):
        integration = vkt.external.OAuth2Integration("aps-integration-design")
        token = integration.get_access_token()
        
        autodesk_file = params.step_ifc.visualize.output_file
        if not autodesk_file:
            raise vkt.UserError("Please select the updated Revit file in the 'View Updated Model' section")
        
        # Get the URN and encode it
        version = autodesk_file.get_latest_version(token)
        urn = version.urn
        encoded_urn = base64.urlsafe_b64encode(urn.encode()).decode().rstrip("=")
        
        return APSResult(urn=encoded_urn, token=token)

    def process_with_workitem(self, params, **kwargs):
        """
        Process the CAD file with Design Automation to add type parameters using ACC,
        then display the updated model in APS Viewer.
        """
        # Get OAuth2 integration for APS
        integration = vkt.external.OAuth2Integration("aps-integration-design")
        access_token = integration.get_access_token()

        try:
            vkt.UserMessage.info("Starting Design Automation workflow with ACC...")
            vkt.progress_message("Preparing files...", percentage=5)

            # Step 1: Get dynamic values from user's selected Revit file
            rvt_file = params.step_params.inputs.input_file
            if not rvt_file:
                raise vkt.UserError("Please select an input Revit file")
            
            PROJECT_ID = rvt_file.project_id
            INPUT_ITEM_LINEAGE_URN = rvt_file.urn
            integration = vkt.external.OAuth2Integration("aps-integration-design")
            token = integration.get_access_token()
            version = rvt_file.get_latest_version(token)
            attrs = version.attributes  # dict
            display_name = attrs.get("displayName", "model")
            vkt.UserMessage.info(f"Project ID: {PROJECT_ID}")
            
            # Detect Revit version from manifest
            vkt.UserMessage.info("Detecting Revit version from model...")
            try:
                manifest = fetch_manifest(params.step_params.inputs.input_file, access_token)
                revit_version = get_revit_version_from_manifest(manifest)
                if not revit_version:
                    revit_version = DEFAULT_REVIT_VERSION
                    vkt.UserMessage.info(f"Could not detect Revit version, using default: {revit_version}")
                else:
                    vkt.UserMessage.info(f"Detected Revit Version: {revit_version}")
            except Exception as e:
                revit_version = DEFAULT_REVIT_VERSION
                vkt.UserMessage.info(f"Error detecting Revit version: {e}, using default: {revit_version}")
            
            # Get the correct signature and activity alias for this Revit version
            signature, activity_full_alias = get_type_parameters_signature(revit_version)
            vkt.UserMessage.info(f"Using activity: {activity_full_alias} for Revit {revit_version}")
            
            vkt.UserMessage.info("Resolving target folder from input file location...")
            vkt.progress_message("Setting up Design Automation with ACC...", percentage=15)

            # Step 2: Create input parameter for Revit file
            vkt.UserMessage.info("Setting up input Revit file from ACC...")
            input_revit = ActivityInputParameterAcc(
                name="rvtFile",
                localName="input.rvt",
                verb="get",
                description="Input Revit File",
                required=True,
                is_engine_input=True,
                project_id=PROJECT_ID,
                linage_urn=INPUT_ITEM_LINEAGE_URN,
            )
            
            # Step 3: Get folder ID from input file location
            folder_id = parent_folder_from_item(
                project_id=PROJECT_ID, 
                item_id=INPUT_ITEM_LINEAGE_URN, 
                token=access_token
            )
            vkt.UserMessage.info(f"Target folder resolved: {folder_id}")
            vkt.progress_message("Generating parameter configuration...", percentage=25)

            # Step 4: Create JSON configuration from params
            vkt.UserMessage.info("Generating parameter configuration...")
            type_params_config = self.create_json_from_params(params)
            vkt.UserMessage.info(f"   Adding {len(type_params_config)} parameter(s)")
            
            # Step 5: Create JSON input parameter to upload to ACC
            input_json = ActivityJsonParameter(
                name="configJson",
                file_name="revit_type_params.json",
                localName="revit_type_params.json",
                verb="get",
                description="Type parameter JSON configuration",
            )
            input_json.set_content(type_params_config)
            vkt.progress_message("Uploading configuration to ACC...", percentage=30)
            
            # Step 6: Create output parameter for result file
            short_uuid = uuid.uuid4().hex[:8]
            output_filename = f"{display_name}_{short_uuid}.rvt"
            output_file = ActivityOutputParameterAcc(
                name="result",
                localName="output.rvt",
                verb="put",
                description="Result Revit model with added parameters",
                folder_id=folder_id,
                project_id=PROJECT_ID,
                file_name=output_filename
            )
            
            # Step 7: Create and execute work item
            vkt.UserMessage.info("Creating work item...")
            vkt.progress_message("Running Design Automation (this may take a few minutes)...", percentage=35)
            
            workitem = WorkItemAcc(
                parameters=[input_revit, input_json, output_file],
                activity_full_alias=activity_full_alias
            )
            workitem_id = workitem.run_public_activity(
                token3lo=access_token, 
                activity_signature=signature
            )
            vkt.UserMessage.info(f"Workitem ID: {workitem_id}")

            # Step 8: Poll workitem status
            vkt.UserMessage.info("Polling workitem status...")
            elapsed = 0
            poll_interval = 10
            max_wait = 600
            final_status = None
            report_url = None

            while elapsed <= max_wait:
                s = get_workitem_status(workitem_id, access_token)
                final_status = s.get("status")
                report_url = s.get("reportUrl")
                percentage = min(35 + int((elapsed / max_wait) * 55), 90)
                vkt.progress_message(f"Work item status: {final_status} [{elapsed}s]...", percentage=percentage)
                vkt.UserMessage.info(f"[{elapsed:3d}s] status = {final_status}")
                if final_status in ("success", "failed", "cancelled"):
                    break
                time.sleep(poll_interval)
                elapsed += poll_interval

            if final_status != "success":
                msg = f"Automation did not finish with success. Status: {final_status}"
                if report_url:
                    msg += f"\nReport URL: {report_url}"
                raise vkt.UserError(msg)

            # Step 9: Create ACC Item for the output
            vkt.UserMessage.info("Work item completed successfully!")
            vkt.progress_message("Creating ACC item for output...", percentage=92)
            vkt.UserMessage.info("Creating ACC Item for the output...")
            output_file.create_acc_item(token=access_token)
            
            vkt.progress_message("Updated model ready for viewing!", percentage=100)

            success_msg = (
                f"Automation completed successfully!\n\n"
                f"Added parameters to Revit types:\n"
                f"- {len(type_params_config)} parameter configuration(s)\n"
                f"- Total targets: {sum(len(p['Targets']) for p in type_params_config)}\n\n"
                f"Workitem ID: {workitem_id}\n"
            )
            if report_url:
                success_msg += f"\nReport URL: {report_url}"

            vkt.UserMessage.success(success_msg)

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            raise vkt.UserError(f"Error in Automation workflow: {str(e)}\n\nDetails:\n{error_detail}")
    
    @staticmethod
    def create_json_from_params(params, **kwargs) -> list[dict[str, Any]]:
        """
        Create JSON configuration for type parameters.
        Groups all targets by parameter name and parameter group.
        Returns an array of parameter configurations, one for each unique parameter.
        """
        # Group rows by (parameter_name, parameter_group)
        grouped = defaultdict(list)
        
        for row in params.step_params.table_section.targets:
            key = (row["parameter_name"], row["parameter_group"])
            grouped[key].append({
                "TypeName": row["type_name"],
                "FamilyName": row["family_name"],
                "Value": row["value"]
            })
        
        # Build the result array
        result = []
        for (param_name, param_group), targets in grouped.items():
            result.append({
                "ParameterName": param_name,
                "ParameterGroup": param_group,
                "Targets": targets
            })
        
        return result

    def export_to_ifc(self, params, **kwargs):
        """
        Export the Revit model to IFC format using Design Automation with ACC.
        Returns a DownloadResult with the exported IFC ZIP file.
        """
        # Get OAuth2 integration for APS
        integration = vkt.external.OAuth2Integration("aps-integration-design")
        access_token = integration.get_access_token()

        try:
            vkt.UserMessage.info("Starting IFC Export workflow with ACC...")
            vkt.progress_message("Preparing files...", percentage=5)

            # Step 1: Validate inputs
            rvt_file = params.step_ifc.visualize.output_file
            if not rvt_file:
                raise vkt.UserError("Please select the updated Revit file in the 'View Updated Model' section")
            
            if not params.step_ifc.inputs.selected_views_for_ifc:
                raise vkt.UserError("Please select at least one view to export to IFC.")

            PROJECT_ID = rvt_file.project_id
            INPUT_ITEM_LINEAGE_URN = rvt_file.urn
            
            vkt.UserMessage.info(f"Project ID: {PROJECT_ID}")
            
            # Step 2: Detect Revit version from manifest
            vkt.UserMessage.info("Detecting Revit version from model...")
            try:
                manifest = fetch_manifest(params.step_ifc.visualize.output_file, access_token)
                revit_version = get_revit_version_from_manifest(manifest)
                if not revit_version:
                    revit_version = DEFAULT_REVIT_VERSION
                    vkt.UserMessage.info(f"Could not detect Revit version, using default: {revit_version}")
                else:
                    vkt.UserMessage.info(f"Detected Revit Version: {revit_version}")
            except Exception as e:
                revit_version = DEFAULT_REVIT_VERSION
                vkt.UserMessage.info(f"Error detecting Revit version: {e}, using default: {revit_version}")
            
            # Step 3: Get the correct signature and activity alias for IFC export
            signature, activity_full_alias = get_ifc_export_signature(revit_version)
            vkt.UserMessage.info(f"Using IFC export activity: {activity_full_alias} for Revit {revit_version}")
            
            vkt.UserMessage.info("Resolving target folder from input file location...")
            vkt.progress_message("Setting up Design Automation with ACC...", percentage=15)

            # Step 4: Create input parameter for Revit file
            vkt.UserMessage.info("Setting up input Revit file from ACC...")
            input_revit = ActivityInputParameterAcc(
                name="rvtFile",
                localName="input.rvt",
                verb="get",
                description="Input Revit File for IFC export",
                required=True,
                is_engine_input=True,
                project_id=PROJECT_ID,
                linage_urn=INPUT_ITEM_LINEAGE_URN,
            )
            
            # Step 5: Get folder ID from input file location
            folder_id = parent_folder_from_item(
                project_id=PROJECT_ID, 
                item_id=INPUT_ITEM_LINEAGE_URN, 
                token=access_token
            )
            vkt.UserMessage.info(f"Target folder resolved: {folder_id}")
            vkt.progress_message("Preparing IFC export settings...", percentage=25)

            # Step 6: Create IFC export configuration
            vkt.UserMessage.info(f"Creating IFC export configuration for {len(params.step_ifc.inputs.selected_views_for_ifc)} view(s)...")
            ifc_config = create_ifc_export_json(params.step_ifc.inputs.selected_views_for_ifc)
            
            input_json = ActivityJsonParameter(
                name="ifcSettings",
                file_name="ifc_settings.json",
                localName="ifc_settings.json",
                verb="get",
                description="IFC Export Settings",
            )
            input_json.set_content(ifc_config)
            vkt.progress_message("Uploading IFC configuration to ACC...", percentage=30)
            
            # Step 7: Create output parameter for ZIP file (stored in ACC)
            # Get display name from the input file
            version = rvt_file.get_latest_version(access_token)
            attrs = version.attributes
            display_name = attrs.get("displayName", "model")
            short_uuid = uuid.uuid4().hex[:8]
            output_zip_filename = f"{display_name}_IFC_{short_uuid}.zip"
            
            output_zip = ActivityOutputParameterAcc(
                name="result",
                localName="result.zip",
                verb="put",
                description="Zipped IFC files",
                folder_id=folder_id,
                project_id=PROJECT_ID,
                file_name=output_zip_filename
            )
            
            # Step 8: Create and execute work item
            vkt.UserMessage.info("Creating IFC export work item...")
            vkt.progress_message("Running IFC Export (this may take a few minutes)...", percentage=35)
            
            workitem = WorkItemAcc(
                parameters=[input_revit, input_json, output_zip],
                activity_full_alias=activity_full_alias
            )
            workitem_id = workitem.run_public_activity(
                token3lo=access_token, 
                activity_signature=signature
            )
            vkt.UserMessage.info(f"Workitem ID: {workitem_id}")

            # Step 9: Poll workitem status
            vkt.UserMessage.info("Polling workitem status...")
            elapsed = 0
            poll_interval = 10
            max_wait = 600
            final_status = None
            report_url = None

            while elapsed <= max_wait:
                s = get_workitem_status(workitem_id, access_token)
                final_status = s.get("status")
                report_url = s.get("reportUrl")
                percentage = min(35 + int((elapsed / max_wait) * 55), 90)
                vkt.progress_message(f"Work item status: {final_status} [{elapsed}s]...", percentage=percentage)
                vkt.UserMessage.info(f"[{elapsed:3d}s] status = {final_status}")
                if final_status in ("success", "failed", "cancelled"):
                    break
                time.sleep(poll_interval)
                elapsed += poll_interval

            if final_status != "success":
                msg = f"IFC export did not finish with success. Status: {final_status}"
                if report_url:
                    msg += f"\nReport URL: {report_url}"
                raise vkt.UserError(msg)

            # Step 10: Create ACC Item for the output
            vkt.UserMessage.info("IFC export completed successfully!")
            vkt.progress_message("Creating ACC item for IFC output...", percentage=92)
            vkt.UserMessage.info("Creating ACC Item for the IFC export...")
            output_zip.create_acc_item(token=access_token)
            
            vkt.progress_message("IFC export complete!", percentage=100)

            success_msg = (
                f"IFC Export completed successfully!\n\n"
                f"Exported views: {len(params.step_ifc.inputs.selected_views_for_ifc)}\n"
                f"- {', '.join(params.step_ifc.inputs.selected_views_for_ifc)}\n\n"
                f"Output file: IFC_Export.zip\n"
                f"Workitem ID: {workitem_id}\n"
            )
            if report_url:
                success_msg += f"\nReport URL: {report_url}"

            vkt.UserMessage.success(success_msg)

        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            raise vkt.UserError(f"Error in IFC Export workflow: {str(e)}\n\nDetails:\n{error_detail}")


