import os
import ctypes
from typing import Any, Optional


class CLibraryWrapper:
    """
    A wrapper class for loading and calling functions from C shared libraries (.so files).

    This class provides a convenient interface to load C shared libraries and call
    their functions from Python using ctypes.
    """

    def __init__(self, library_path: str):
        """
        Initialize the CLibraryWrapper with the path to the C shared library.

        Args:
            library_path (str): Path to the C shared library (.so file)

        Raises:
            FileNotFoundError: If the library file does not exist
            OSError: If the library cannot be loaded
        """
        if not os.path.exists(library_path):
            raise FileNotFoundError(f"C library file not found: {library_path}")

        try:
            # Load the shared library
            self._library = ctypes.CDLL(library_path)
            self._library_path = library_path
        except OSError as e:
            raise OSError(f"Failed to load C library: {e}")

    def get_function(
        self,
        func_name: str,
        restype: Any = ctypes.c_void_p,
        argtypes: Optional[list] = None,
    ):
        """
        Get a function from the loaded C library with specified return type and argument types.

        Args:
            func_name (str): Name of the function in the C library
            restype (Any, optional): Return type of the function (default: ctypes.c_void_p)
            argtypes (list, optional): List of argument types for the function (default: None)

        Returns:
            ctypes._FuncPtr: A callable function object

        Raises:
            AttributeError: If the function does not exist in the library
        """
        try:
            # Get the function from the library
            func = getattr(self._library, func_name)

            # Set return type
            func.restype = restype

            # Set argument types if provided
            if argtypes is not None:
                func.argtypes = argtypes

            return func
        except AttributeError:
            raise AttributeError(
                f"Function '{func_name}' not found in library '{self._library_path}'"
            )

    def call_function(
        self,
        func_name: str,
        *args,
        restype: Any = ctypes.c_void_p,
        argtypes: Optional[list] = None,
    ) -> Any:
        """
        Call a function from the loaded C library with the given arguments.

        Args:
            func_name (str): Name of the function in the C library
            *args: Arguments to pass to the function
            restype (Any, optional): Return type of the function (default: ctypes.c_void_p)
            argtypes (list, optional): List of argument types for the function (default: None)

        Returns:
            Any: The return value from the C function

        Raises:
            AttributeError: If the function does not exist in the library
            TypeError: If the arguments do not match the expected types
            Exception: If the C function call fails
        """
        func = self.get_function(func_name, restype, argtypes)

        try:
            return func(*args)
        except TypeError as e:
            raise TypeError(f"Failed to call function '{func_name}': {e}")
        except Exception as e:
            raise Exception(f"Error calling function '{func_name}': {e}")

    @property
    def library_path(self) -> str:
        """Get the path to the loaded library."""
        return self._library_path

    @property
    def is_loaded(self) -> bool:
        """Check if the library is loaded successfully."""
        return hasattr(self, '_library') and self._library is not None


def load_c_library(library_path: str) -> CLibraryWrapper:
    """
    Convenience function to create and return a CLibraryWrapper instance.

    Args:
        library_path (str): Path to the C shared library (.so file)

    Returns:
        CLibraryWrapper: An instance of CLibraryWrapper for the specified library
    """
    return CLibraryWrapper(library_path)


# Example usage
if __name__ == "__main__":
    """
    Example demonstrating how to use the CLibraryWrapper class.

    This example assumes you have a shared library named "libexample.so"
    with a function "int add(int a, int b)".
    """
    try:
        # Replace with your actual library path
        lib_path = "./libexample.so"

        # Create wrapper instance
        lib_wrapper = CLibraryWrapper(lib_path)

        # Call a function with explicit type specification
        result = lib_wrapper.call_function(
            "add", 10, 20, restype=ctypes.c_int, argtypes=[ctypes.c_int, ctypes.c_int]
        )

        print(f"Result of add(10, 20): {result}")

    except Exception as e:
        print(f"Error: {e}")
