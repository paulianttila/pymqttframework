#!/bin/bash

. env

DIR_CA="ca"
DIR_SERVER="server"
DIR_CLIENT="client"

FILE_CA="${DIR_CA}/ca"

function generate_CA () {
  echo "Generating Certificate Authority: ${CN_CA}"
  
  SUBJECT_CA="/C=${C}/O=${O}/CN=${CN_CA}"
  openssl req -x509 -nodes -sha256 -newkey rsa:${ROOT_KEY_LEN} -subj "${SUBJECT_CA}"  -days "${CERT_VALID_DAYS}" -keyout ${FILE_CA}.key -out ${FILE_CA}.crt
  openssl x509 -in ${FILE_CA}.crt -noout -text
  chmod 400 ${FILE_CA}.key
  chmod 444 ${FILE_CA}.crt
}

function generate_server () {
  if [ -z "$1" ]; then
    echo "Server certifcate filename parameter missing"
    exit 1
  fi
  if [ -z "$2" ]; then
    echo "Server certifcate CommonName parameter missing"
    exit 1
  fi
  if [ -z "$3" ]; then
    echo "Server certifcate AltName parameter missing"
    exit 1
  fi
  
  FILE="${DIR_SERVER}/$1"
  CN=$2
  ALTNAMES=$3
  
  if [ -f "${FILE}.key" ] || [ -f "${FILE}.crt" ]; then
    echo "Server certificate files already exists...aborting"
    exit 1
  fi

  echo "Generating Server Certificate: ${CN}"
  
  SUBJECT_SERVER="/C=${C}/O=${O}/CN=${CN}"
  openssl req -nodes -sha256 -new -subj "${SUBJECT_SERVER}" -addext "subjectAltName=${ALTNAMES}" -newkey rsa:${KEY_LEN} -keyout ${FILE}.key -out ${FILE}.csr
  openssl x509 -req -sha256 -in ${FILE}.csr -extfile <(printf "subjectAltName=${ALTNAMES}") -CA ${FILE_CA}.crt -CAkey ${FILE_CA}.key -CAcreateserial -out ${FILE}.crt -days "${CERT_VALID_DAYS}"
  openssl x509 -in ${FILE}.crt -noout -text 
  rm ${FILE}.csr
  chmod 400 ${FILE}.key
  chmod 444 ${FILE}.crt
}

function generate_client () {
  if [ -z "$1" ]; then
    echo "Client certifcate filename parameter missing"
    exit 1
  fi
  if [ -z "$2" ]; then
    echo "Client certifcate CommonName parameter missing"
    exit 1
  fi
  
  FILE="${DIR_CLIENT}/$1"
  CN=$2

  if [ -f "${FILE}.key" ] || [ -f "${FILE}.crt" ]; then
    echo "Client certificate files already exists...aborting"
    exit 1
  fi

  SUBJECT_CLIENT="/C=${C}/O=${O}/CN=${CN}"
  echo "Generating client certificate: ${CN}"
  openssl req -new -nodes -sha256 -subj "${SUBJECT_CLIENT}" -newkey rsa:${KEY_LEN} -keyout ${FILE}.key -out ${FILE}.csr
  openssl x509 -req -sha256 -in ${FILE}.csr -CA ${FILE_CA}.crt -CAkey ${FILE_CA}.key -CAcreateserial -out ${FILE}.crt -days "${CERT_VALID_DAYS}"
  openssl x509 -in ${FILE}.crt -noout -text
  rm ${FILE}.csr
  chmod 400 ${FILE}.key
  chmod 444 ${FILE}.crt
}

function generate_all () {
  if [ -d "${DIR_CA}" ] || [ -d "${DIR_SERVER}" ] || [ -d "${DIR_CLIENT}" ]; then
    echo "Directory '${DIR_CA}', '${DIR_SERVER}' or '${DIR_CLIENT}' already exists...aborting"
    exit 1
  fi

  echo "Generating All"
  mkdir ${DIR_CA}
  mkdir ${DIR_SERVER}
  mkdir ${DIR_CLIENT}
  
  generate_CA
  generate_server "server" "${CN_SERVER}" "${SERVER_ALTNAMES}"
  generate_client "client" "${CN_CLIENT}"
  ls -lR 
}

    
if ! command -v openssl &> /dev/null
then
  echo "openssl not found...aborting"
  exit 1
fi


case $1 in
  "server")
    generate_server "$2" "$3" "$4"
    ;;

  "client")
    generate_client "$2" "$3"
    ;;

  *)
    generate_all
    ;;
esac
