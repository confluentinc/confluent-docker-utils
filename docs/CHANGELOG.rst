Version 0.0.35
--------------------------------------------------------------------------------

* Merge pull request #14 from confluentinc/addCryptography.

* Update requirements.txt.


Version 0.0.34
--------------------------------------------------------------------------------

* Merge pull request #13 from yangxi/paramiko.

* Use ==

* Add paramiko 2.4.2 to the list.


Version 0.0.33
--------------------------------------------------------------------------------

* Pin pytest lib version.


Version 0.0.32
--------------------------------------------------------------------------------

* Merge pull request #12 from confluentinc/ST-1340.

* For KSQL server, change match string from version to Ksql.

* Add info to KSQL server path.

* ST-1340: added ksql-server-ready and control-center-ready.


Version 0.0.31
--------------------------------------------------------------------------------

* Merge pull request #11 from confluentinc/ST-1531.

* Fix comment.

* ST-1531: add connect-ready to cub.


Version 0.0.29
--------------------------------------------------------------------------------

* Move notifications to tools-notifications.

* Move notifications to tools-notifications.

* Tox python2 / python3 fixes (#9)


Version 0.0.27
--------------------------------------------------------------------------------

* Merge pull request #7 from maxzheng/add-cp-base@master.

* Add cp-base-new to the classpath.


Version 0.0.26
--------------------------------------------------------------------------------

* Merge pull request #6 from confluentinc/fixensuretopic
  
  fix the classpath.
* fix the classpath.

Version 0.0.25
--------------------------------------------------------------------------------

* fix style
* pip.req is not needed (#5)

Version 0.0.24
--------------------------------------------------------------------------------

* port fixes from confluentinc/cp-docker-images#372 (#4)

Version 0.0.23
--------------------------------------------------------------------------------

* let add_registry_and_tag be scoped to UPSTREAM or TAG dependencies (#3)

Version 0.0.22
--------------------------------------------------------------------------------

* Add dub path-wait command (#2)

Version 0.0.21
--------------------------------------------------------------------------------

* add add_registry_and_tag function

Version 0.0.20
--------------------------------------------------------------------------------

* deal with NoneType for RepoTags

Version 0.0.19
--------------------------------------------------------------------------------

* handle urlparse for python 2 vs 3

Version 0.0.18
--------------------------------------------------------------------------------

* fix exception syntax

Version 0.0.17
--------------------------------------------------------------------------------

* Revert "Bump requests dependency"
  
  This reverts commit fe4b6bd1e0adf12ee4cd9a1b9adb0ef424af745c.

Version 0.0.16
--------------------------------------------------------------------------------

* Merge branch 'master' of github.com:confluentinc/confluent-docker-utils
* Bump requests dependency

Version 0.0.15
--------------------------------------------------------------------------------

* let each image set CUB_CLASSPATH

Version 0.0.14
--------------------------------------------------------------------------------

* add ensure_topic command

Version 0.0.13
--------------------------------------------------------------------------------

* use DOCKER_HOST env var for API Client

Version 0.0.12
--------------------------------------------------------------------------------

* remove dangling quote

Version 0.0.11
--------------------------------------------------------------------------------

* update classpath, flake8 fixes

Version 0.0.10
--------------------------------------------------------------------------------

* pass in tag as part of image name

Version 0.0.9
--------------------------------------------------------------------------------

* Merge branch 'master' of github.com:confluentinc/confluent-docker-utils
* allow caller to pass in a tag

Version 0.0.8
--------------------------------------------------------------------------------

* add jinja2 to requirements

Version 0.0.7
--------------------------------------------------------------------------------

* Merge branch 'master' of github.com:confluentinc/confluent-docker-utils
* extract cub and dub utilities from cp-docker-images

Version 0.0.6
--------------------------------------------------------------------------------

* fix wording
* add basic README

Version 0.0.5
--------------------------------------------------------------------------------

* update for docker api changes

Version 0.0.4
--------------------------------------------------------------------------------

* Merge branch 'master' of github.com:confluentinc/confluent-docker-utils
* remove unused function
* remove TestMachine and refresh deps

Version 0.0.3
--------------------------------------------------------------------------------

* Merge branch 'master' of github.com:confluentinc/confluent-docker-utils
* remove pytest-sugar

Version 0.0.2
--------------------------------------------------------------------------------

* add basic test
* get ready for jenkins
* extract docker utils lib from cp-docker-images
* Initial commit
