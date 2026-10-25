from app.add_item import AddCustomizationWindow


class EditCustomizationWindow(AddCustomizationWindow):
    """Shared embedded form with an immutable GUID and existing values."""

    def __init__(self, catalog, record, parent=None):
        super().__init__(catalog, record=record, parent=parent)
