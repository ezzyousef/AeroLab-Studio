"""The application's pages. Each owns one job and reads only from the Session."""
from .base import Page
from .home import HomePage
from .calculator import CalculatorPage
from .data import DataPage
from .measure import MeasurePage
from .plots import PlotsPage
from .export import ExportPage
from .validation import ValidationPage
from .settings import SettingsPage
from .about import AboutPage
from .workspace import WorkspacePage
from .mechanics import MechanicsPage
from .materials import MaterialsPage
from .explorer import ExplorerPage

__all__ = ["Page", "HomePage", "CalculatorPage", "DataPage", "MeasurePage", "PlotsPage",
           "ExportPage", "ValidationPage", "SettingsPage", "AboutPage",
           "WorkspacePage", "MechanicsPage", "MaterialsPage", "ExplorerPage"]
