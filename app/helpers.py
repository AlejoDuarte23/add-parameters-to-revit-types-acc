import base64
import os
import requests

from dotenv import load_dotenv
from typing import Any

load_dotenv()

APS_BASE_URL = "https://developer.api.autodesk.com"
MD_BASE_URL = f"{APS_BASE_URL}/modelderivative/v2"

def to_md_urn(wip_urn: str) -> str:
    """Convert WIP URN to Model Derivative URN."""
    raw = wip_urn.split("?", 1)[0]
    encoded = base64.urlsafe_b64encode(raw.encode("utf8")).decode("utf8")
    return encoded.rstrip("=")


def get_revit_version_from_manifest(manifest: dict) -> str | None:
    """Extract Revit version from manifest."""
    try:
        derivatives = manifest.get("derivatives", [])
        if not derivatives:
            return None
        
        for derivative in derivatives:
            properties = derivative.get("properties", {})
            doc_info = properties.get("Document Information", {})
            rvt_version = doc_info.get("RVTVersion")
            if rvt_version:
                return str(rvt_version)
        
        return None
    except Exception as e:
        print(f"Error extracting Revit version from manifest: {e}")
        return None


def fetch_manifest(autodesk_file_param, token):
    """Fetch model derivative manifest."""
    version = autodesk_file_param.get_latest_version(token)
    urn = version.urn
    encoded_urn = base64.urlsafe_b64encode(urn.encode()).decode().rstrip("=")
    url = f"https://developer.api.autodesk.com/modelderivative/v2/designdata/{encoded_urn}/manifest"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()

TYPE_PARAMETERS_CONFIG = {
    "2023": {
        "signature": os.getenv("TypeParametersActivity2023", ""),
        "activity_full_alias": os.getenv("ACTIVITY_FULL_ALIAS_TypeParameters2023", ""),
    },
    "2024": {
        "signature": os.getenv("TypeParametersActivity2024", ""),
        "activity_full_alias": os.getenv("ACTIVITY_FULL_ALIAS_TypeParameters2024", ""),
    },
    "2025": {
        "signature": os.getenv("TypeParametersActivity2025", ""),
        "activity_full_alias": os.getenv("ACTIVITY_FULL_ALIAS_TypeParameters2025", ""),
    },
    "2026": {
        "signature": os.getenv("TypeParametersActivity2026", ""),
        "activity_full_alias": os.getenv("ACTIVITY_FULL_ALIAS_TypeParameters2026", ""),
    }
}

# IFC Export version to activity/engine mapping
# Based on the activities created in autodesk_automation - ExportIFC/create_activities_by_revit_version.ipynb
IFC_EXPORT_VERSION_CONFIG = {
    "2023": {
        "signature": os.getenv("RevitIfcExportAppActivity2023", ""),
        "activity_full_alias": os.getenv("ACTIVITY_FULL_ALIAS_IfcExport2023", ""),
    },
    "2024": {
        "signature": os.getenv("RevitIfcExportAppActivity2024", ""),
        "activity_full_alias": os.getenv("ACTIVITY_FULL_ALIAS_IfcExport2024", ""),
    },
    "2025": {
        "signature": os.getenv("RevitIfcExportAppActivity2025", ""),
        "activity_full_alias": os.getenv("ACTIVITY_FULL_ALIAS_IfcExport2025", ""),
    },
    "2026": {
        "signature": os.getenv("RevitIfcExportAppActivity2026", ""),
        "activity_full_alias": os.getenv("ACTIVITY_FULL_ALIAS_IfcExport2026", ""),
    }
}



# Default to 2024 if version cannot be detected
DEFAULT_REVIT_VERSION = "2024"


def get_type_parameters_signature(revit_version: str | None) -> tuple[str, str]:
    """Get the activity signature and full alias for TypeParameters based on Revit version.
    
    Returns:
        tuple: (signature, activity_full_alias)
    
    Raises:
        ValueError: If the Revit version is not supported.
    """
    if revit_version not in TYPE_PARAMETERS_CONFIG:
        supported = ", ".join(TYPE_PARAMETERS_CONFIG.keys())
        raise ValueError(f"Revit version '{revit_version}' is not supported. Supported versions: {supported}")
    config = TYPE_PARAMETERS_CONFIG[revit_version]
    return config["signature"], config["activity_full_alias"]


def get_ifc_export_signature(revit_version: str | None) -> tuple[str, str]:
    """Get the activity signature and full alias for IFC Export based on Revit version.
    
    Returns:
        tuple: (signature, activity_full_alias)
    
    Raises:
        ValueError: If the Revit version is not supported.
    """
    if revit_version not in IFC_EXPORT_VERSION_CONFIG:
        supported = ", ".join(IFC_EXPORT_VERSION_CONFIG.keys())
        raise ValueError(f"Revit version '{revit_version}' is not supported for IFC export. Supported versions: {supported}")
    config = IFC_EXPORT_VERSION_CONFIG[revit_version]
    return config["signature"], config["activity_full_alias"]


def get_viewables_from_urn(token:str, object_urn: str) -> list[dict[str, Any]]:
    """
    Get available viewables (views) from a translated model.
    """
    
    response = requests.get(
        f"{MD_BASE_URL}/designdata/{object_urn}/manifest",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30
    )
    response.raise_for_status()
    
    manifest = response.json()
    viewables = []
    
    def extract_viewables(children: list, parent_name: str = ""):
        """Recursively extract viewables from manifest children."""
        for child in children:
            role = child.get("role", "")
            guid = child.get("guid", "")
            name = child.get("name", "Unnamed View")
            
            # Viewables typically have role '3d' or '2d'
            if role in ["3d", "2d"] and guid:
                viewables.append({
                    "guid": guid,
                    "name": name,
                    "role": role
                })
            
            # Recurse into nested children
            if "children" in child:
                extract_viewables(child["children"], name)
    
    # Process derivatives
    derivatives = manifest.get("derivatives", [])
    for derivative in derivatives:
        children = derivative.get("children", [])
        extract_viewables(children)
    
    print(f"Found {len(viewables)} viewable(s) in manifest")
    
    return viewables


def get_view_names_from_manifest(manifest: dict) -> list[str]:
    """
    Extract view names from a model derivative manifest for IFC export selection.
    Returns a list of view names that can be used in MultiSelectField options.
    """
    seen = set()
    view_names = []
    
    for derivative in manifest.get("derivatives", []):
        if derivative.get("outputType") in ["svf", "svf2"]:
            for geometry_node in derivative.get("children", []):
                if geometry_node.get("type") == "geometry" and geometry_node.get("role") in ["3d", "2d"]:
                    # base name is the geometry node name
                    base_name = geometry_node.get("name", "")
                    candidate_names = [base_name]
                    # if there is a child of type view with its own name, include that too
                    for child_node in geometry_node.get("children", []):
                        if child_node.get("type") == "view":
                            name = child_node.get("name", "") or base_name
                            candidate_names.append(name)
                    for name in candidate_names:
                        if not name:
                            continue
                        # remove any cosmetic prefixes
                        clean = name.replace("[3D] ", "").replace("[2D] ", "")
                        if clean not in seen:
                            seen.add(clean)
                            view_names.append(clean)
    
    print(f"Found {len(view_names)} view name(s) in manifest")
    return view_names


def create_ifc_export_json(selected_view_names: list[str]) -> dict[str, Any]:
    """
    Create IFC export settings JSON configuration from selected view names.
    """
    config = {
        "view_names": selected_view_names,
        "FileVersion": "IFC4",
        "IFCFileType": "IFC",
        "ExportBaseQuantities": True,
        "SpaceBoundaryLevel": 2,
        "FamilyMappingFile": "",
        "ExportInternalRevitPropertySets": False,
        "ExportIFCCommonPropertySets": True,
        "ExportAnnotations": False,
        "Export2DElements": False,
        "ExportRoomsInView": False,
        "VisibleElementsOfCurrentView": False,
        "ExportLinkedFiles": False,
        "IncludeSteelElements": False,
        "ExportPartsAsBuildingElements": True,
        "UseActiveViewGeometry": False,
        "UseFamilyAndTypeNameForReference": False,
        "Use2DRoomBoundaryForVolume": False,
        "IncludeSiteElevation": False,
        "ExportBoundingBox": False,
        "ExportSolidModelRep": False,
        "StoreIFCGUID": False,
        "ExportSchedulesAsPsets": False,
        "ExportSpecificSchedules": False,
        "ExportUserDefinedPsets": False,
        "ExportUserDefinedPsetsFileName": "",
        "ExportUserDefinedParameterMapping": False,
        "ExportUserDefinedParameterMappingFileName": "",
        "ActivePhase": "",
        "SitePlacement": 0,
        "TessellationLevelOfDetail": 0.0,
        "UseOnlyTriangulation": False
    }
    
    return config