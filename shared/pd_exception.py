class PDException(Exception):
    pass

class OperationalException(PDException):
    pass

class ParseException(PDException):
    pass

class InvalidDataException(PDException):
    pass

class DatabaseException(PDException):
    pass

class DoesNotExistException(PDException):
    pass

class TooManyItemsException(PDException):
    pass