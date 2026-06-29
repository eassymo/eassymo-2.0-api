def get_successful_response(body):
    return {
        "body": body
    }


def get_unsuccessful_response(exception: Exception):
    return {
        "error": str(exception)
    }
