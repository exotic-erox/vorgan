{ lib
, python3
}:

python3.pkgs.buildPythonApplication {
  pname = "vorgan";
  version = "0.1.0";
  format = "pyproject";

  src = ../.;

  build-system = with python3.pkgs; [
    setuptools
    wheel
  ];

  propagatedBuildInputs = with python3.pkgs; [
    textual
    pillow
  ];

  meta = with lib; {
    description = "A mouse-and-keyboard terminal file manager with the Graph navigator";
    homepage = "https://github.com/exotic-erox/vorgan";
    license = licenses.mit;
    mainProgram = "vorgan";
  };
}
