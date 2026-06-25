VARIABLE BUF
: PRINT 
    DUP @ SWAP 1 + SWAP 
    BEGIN DUP 0 > 
    WHILE OVER @ 1 OUT SWAP 1 + SWAP 1 - 
    REPEAT DROP DROP ;
: READ-NAME 
    BUF 1 + 
    BEGIN 0 IN DUP 0 > 
    WHILE OVER ! 1 + 
    REPEAT DROP BUF 1 + - BUF ! ;
: MAIN 
    P" What is your name? " 
    PRINT READ-NAME P" Hello, " 
    PRINT BUF 
    PRINT P"!" 
    PRINT ;
MAIN