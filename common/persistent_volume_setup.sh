##Use this to create symlink with the actual folders/directories where conda environment will be installed or provisioined
ln -sfvn /opt/app-root/<name-of-pv>/$APP_NAME_PV/$PV_COLOR/conda /opt/app-root/src/conda-venv
## In order to manage multiple instances of the application, you can use $APP_NAME_PV to name the instance like JupyterHub_V1 .
##In order to maanage multiple version of the same application instance for Blue-Green Deployment, PV_COLOR can be used as an environment variable.
