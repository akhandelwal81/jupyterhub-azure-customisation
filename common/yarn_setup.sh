##This is predominantly used if you need to enable any JupyerHub UI Extensions that need the UI to be rebuild
##there are numerous occassions where the users get confused between the Yarn Resource Manager and Yarn UI tool
## This script can allow you to switch between Hadoop Yarn and NPM Yarn

if [["$1" == "hadoop"]]; then
     mv -v ${HOME}/jupyter-conda/conda/envs/env1/bin/yarn ${HOME}/jupyter-conda/conda/envs/env1/bin-yarn-backup
     mv -v ${HOME}/hadoop/client/bin/yarn-backup ${HOME}/hadoop/client/bin/yarn

elif [[ "$1"=="npm" ]]; then
    mv -v ${HOME}/jupyter-conda/conda/envs/env1/bin/yarn-backup ${HOME}/jupyter-conda/conda/envs/env1/bin/yarn

fi
