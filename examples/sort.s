VARIABLE ADDR1
VARIABLE ADDR2
VARIABLE V1
VARIABLE V2
VARIABLE ARR
: READ-ARR 
    0 IN ARR ! ARR @ 0 
    DO 0 IN 100 I + ! 
    LOOP ;
: BUBBLE-SORT ARR @ 1 - 0 
    DO ARR @ 1 - I - 0 
        DO 100 I + ADDR1 ! 101 I + ADDR2 ! ADDR1 @ @ ADDR2 @ @ > 
            IF ADDR1 @ @ V1 ! ADDR2 @ @ V2 ! V1 @ ADDR2 @ ! V2 @ ADDR1 @ ! 
            THEN 
        LOOP 
    LOOP ;
: PRINT-ARR ARR @ 0 
    DO 100 I + @ 1 OUT 
    LOOP ;
: MAIN 
    READ-ARR 
    BUBBLE-SORT 
    PRINT-ARR ;
MAIN