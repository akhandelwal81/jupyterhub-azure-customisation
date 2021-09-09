
echo "Running init_conda_venv.sh -----------"

#Set beow by conda activate
export PYTHON_VERSION=
expot PYTHONPATH=

# You would need a Persistent Storage to store teh Python Virtual environment.
#Once you have mounted the virtual environment, the environment value below would help in setting the home directory for conda
export CONDA_PVC = /opt/app-root/src/jupyter-conda/conda

echo "Conda home set to: $CONDA_PVC_HOME"

__conda_setup ="$('/opt/app-root/src/jupyter-conda/conda/bin/conda' 'shell.bash' 'hook' 2> /dev/null)"
if [$? -eq 0]; then
  echo "==> evaluating conda setup"
  eval "$__conda_setup"
else
  if [-f "${CONDA_PVC_HOME}/etc/profile.d/conda.sh"]; then
    echo "==> running conda.sh:"
    . "${CONDA_PVC_HOME}/etc/profile.d/conda.sh"
  else
    echo "==> exporting path:"
    export PATH="{CONDA_PVC_HOME}/conda/bin:$PATH"
  fi
fi
unset __conda_setup
echo "==> activate conda env:"
conda activate <name of virtual environment>
