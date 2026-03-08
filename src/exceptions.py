class SyncError(Exception): pass
class ConnectorError(SyncError): pass
class MappingError(SyncError): pass
class ConflictError(SyncError): pass
class ReconciliationError(SyncError): pass
class SchedulerError(SyncError): pass
