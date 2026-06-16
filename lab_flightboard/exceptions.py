class LabFlightboardError(Exception):
    pass


class CalendarFetchError(LabFlightboardError):
    pass


class CalendarParseError(LabFlightboardError):
    pass


class EquipmentConfigError(LabFlightboardError):
    pass


class BillboardConfigError(LabFlightboardError):
    pass
