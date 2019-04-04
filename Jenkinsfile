def defaultConfig = [
  owner: 'tools',
  slackChannel: 'tools-eng',
  runMergeCheck: false,  // Python tooling is strictly trunk dev
  testResultSpecs: ['junit': 'test/results.xml']
]
def config = jobConfig(body, defaultConfig)

def job = {
  withCredentials([
      usernamePassword(credentialsId: 'Jenkins Nexus Account', passwordVariable: 'NEXUS_PASSWORD',
                       usernameVariable: 'NEXUS_USERNAME'),
      usernameColonPassword(credentialsId: 'Jenkins GitHub Account', variable: 'GIT_CREDENTIAL')]) {
          sshagent(['ConfluentJenkins Github SSH Key']) {
              withEnv(['PYTESTARGS=--junitxml=test/results.xml']) {
                  stage("Setup") {
                      // We should probably convert these to Groovy script at one point so we don't need to load/write resources.
                      writeFile file:'create-pip-conf-with-nexus.sh', text:libraryResource('scripts/create-pip-conf-with-nexus.sh')
                      writeFile file:'create-pypirc-with-nexus.sh', text:libraryResource('scripts/create-pypirc-with-nexus.sh')
                      writeFile file:'setup-credential-store.sh', text:libraryResource('scripts/setup-credential-store.sh')
                      writeFile file:'set-global-user.sh', text:libraryResource('scripts/set-global-user.sh')

                      sh '''
                          bash create-pip-conf-with-nexus.sh
                          bash create-pypirc-with-nexus.sh
                          bash setup-credential-store.sh
                          bash set-global-user.sh
                      '''

                  }

                  stage("Test") {
                     withDockerServer([uri: dockerHost()]) {
                        sh 'tox'
                     }
                  }

                  if (config.publish && config.isDevJob) {
                      stage('Publish') {
                          sh '''
                              git checkout $BRANCH_NAME
                              git reset --hard
                              python3 -m venv /tmp/venv
                              . /tmp/venv/bin/activate
                              pip install workspace-tools==3.3.7
                              wst publish --repo nexus
                          '''
                      }
                  }
              }
          }
      }
}

def post = {
  stage("Reports") {
      junit allowEmptyResults: true, testResults: 'test/results.xml'
      publishHTML([allowMissing: true, alwaysLinkToLastBuild: true, keepAll: true, reportDir: 'htmlcov', reportFiles: 'index.html', reportName: 'Coverage Report', reportTitles: ''])
  }
}

runJob config, job, post
